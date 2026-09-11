#include "museboard/encoder.hpp"
#include "museboard/processing.hpp"
#include <array>
#include <stdexcept>

// Loads CLIP once and reuses the inference session across images.

namespace museboard {
Encoder::Encoder(const std::filesystem::path& model) {
    options_.SetIntraOpNumThreads(2);
    options_.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
    session_ = Ort::Session(env_, model.c_str(), options_);
    Ort::AllocatorWithDefaultOptions allocator;
    if (session_.GetInputCount() != 1 ||
        std::string(session_.GetInputNameAllocated(0, allocator).get()) != "pixel_values")
        throw std::runtime_error("Expected the pinned CLIP vision-only ONNX model (pixel_values input)");
}
std::vector<float> Encoder::encode(const cv::Mat& bgr) {
    auto pixels = clip_input(bgr);
    const std::array<int64_t, 4> shape{1, 3, 224, 224};
    auto memory = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
    auto input = Ort::Value::CreateTensor<float>(memory, pixels.data(), pixels.size(), shape.data(), shape.size());
    const char* inputs[] = {"pixel_values"};
    const char* outputs[] = {"image_embeds"};
    auto result = session_.Run(Ort::RunOptions{nullptr}, inputs, &input, 1, outputs, 1);
    const auto info = result[0].GetTensorTypeAndShapeInfo();
    if (info.GetElementType() != ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT ||
        info.GetShape() != std::vector<int64_t>{1, 512})
        throw std::runtime_error("Expected float32 image_embeds with shape [1,512]");
    const auto* data = result[0].GetTensorData<float>();
    std::vector<float> embedding(data, data + 512);
    normalize(embedding);
    return embedding;
}
}
