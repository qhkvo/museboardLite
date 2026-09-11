#pragma once
#include <onnxruntime_cxx_api.h>
#include <opencv2/core.hpp>
#include <filesystem>
#include <vector>

// Encodes images into 512-dimensional CLIP embeddings using the pinned vision-only ONNX model.

namespace museboard {
inline constexpr const char* model_id =
    "Xenova/clip-vit-base-patch32@d15189d7028b43f1d3e65039190477f6af591c2a/onnx/vision_model.onnx";
class Encoder {
public:
    explicit Encoder(const std::filesystem::path& model);
    std::vector<float> encode(const cv::Mat& bgr);
private:
    Ort::Env env_{ORT_LOGGING_LEVEL_WARNING, "museboard"};
    Ort::SessionOptions options_;
    Ort::Session session_{nullptr};
};
}
