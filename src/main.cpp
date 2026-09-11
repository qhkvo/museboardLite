#include "museboard/encoder.hpp"
#include "museboard/processing.hpp"
#include <opencv2/imgcodecs.hpp>
#include <algorithm>
#include <chrono>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>

// Runs the batch, writes outputs, reports failures, and ranks matches.

namespace fs = std::filesystem;
using Clock = std::chrono::steady_clock;
static double milliseconds(Clock::time_point start) {
    return std::chrono::duration<double, std::milli>(Clock::now() - start).count();
}
static std::string quote(const std::string& value) {
    std::ostringstream out;
    out << '"';
    for (unsigned char c : value) {
        if (c == '"' || c == '\\') out << '\\' << c;
        else if (c < 32) out << "\\u" << std::hex << std::setfill('0') << std::setw(4) << int(c);
        else out << c;
    }
    return out.str() + '"';
}
static void save(const fs::path& path, const std::string& text) {
    std::ofstream out(path);
    if (!(out << text)) throw std::runtime_error("Cannot write: " + path.string());
}
struct Result { fs::path input; std::string directory; std::vector<float> embedding; };

int main(int argc, char** argv) {
    try {
        fs::path model = "models/vision_model.onnx", output;
        std::vector<fs::path> images;
        bool positional = false;
        for (int i = 1; i < argc; ++i) {
            std::string arg = argv[i];
            if (!positional && arg == "--") { positional = true; continue; }
            if (!positional && (arg == "--help" || arg == "-h")) {
                std::cout << "Usage: museboard-prototype --output NEW_DIRECTORY [--model MODEL.onnx] IMAGE [IMAGE ...]\n"
                             "Processes JPEG/PNG images, writes thumbnails + result.json, and ranks cosine similarity.\n"
                             "The output directory must not exist. Use -- before filenames starting with '-'.\n";
                return 0;
            }
            if (!positional && (arg == "--model" || arg == "--output")) {
                if (++i == argc) throw std::invalid_argument("Missing value for " + arg);
                (arg == "--model" ? model : output) = argv[i];
            } else if (!positional && arg.starts_with('-')) {
                throw std::invalid_argument("Unknown option: " + arg);
            } else images.emplace_back(fs::weakly_canonical(fs::absolute(arg)));
        }
        if (images.empty() || output.empty()) throw std::invalid_argument("Provide --output NEW_DIRECTORY and at least one image; see --help");
        if (!fs::is_regular_file(model)) throw std::runtime_error("Model missing. Run python3 scripts/download_model.py first");
        // Cap decoder allocation before imread (OpenCV reads this setting on first use).
        setenv("OPENCV_IO_MAX_IMAGE_PIXELS", "40000000", 0);
        setenv("OPENCV_IO_MAX_IMAGE_WIDTH", "16384", 0);
        setenv("OPENCV_IO_MAX_IMAGE_HEIGHT", "16384", 0);
        const auto model_start = Clock::now();
        museboard::Encoder encoder(model);
        const auto model_ms = milliseconds(model_start);
        if (fs::exists(output)) throw std::runtime_error("Output already exists; choose a new directory: " + output.string());
        if (!fs::create_directories(output)) throw std::runtime_error("Could not create output directory");
        std::vector<Result> results;
        int failures = 0;
        for (size_t index = 0; index < images.size(); ++index) {
            try {
                const auto start = Clock::now();
                const auto image = museboard::load_image(images[index]);
                auto thumb = museboard::thumbnail(image);
                const auto colors = museboard::palette(image);
                const auto cpu_ms = milliseconds(start);
                const auto ai_start = Clock::now();
                auto embedding = encoder.encode(image);
                const auto ai_ms = milliseconds(ai_start);
                const auto directory = "image-" + std::to_string(index + 1);
                const auto destination = output / directory;
                fs::create_directory(destination);
                if (!cv::imwrite((destination / "thumbnail.jpg").string(), thumb))
                    throw std::runtime_error("Cannot save thumbnail");
                std::ostringstream json;
                json << std::setprecision(9)
                     << "{\n  \"source\": " << quote(images[index].string())
                     << ",\n  \"width\": " << image.cols << ", \"height\": " << image.rows
                     << ",\n  \"thumbnail\": \"thumbnail.jpg\",\n  \"model_id\": " << quote(museboard::model_id)
                     << ",\n  \"preprocessing_id\": \"clip-pillow-bicubic-v1\",\n  \"embedding_dimension\": 512,\n  \"palette\": [";
                for (size_t i = 0; i < colors.size(); ++i) {
                    const auto& c = colors[i];
                    json << (i ? "," : "") << "\n    {\"hex\": " << quote(c.hex) << ", \"weight\": " << c.weight
                         << ", \"lab\": [" << c.lab[0] << ", " << c.lab[1] << ", " << c.lab[2] << "]}";
                }
                json << "\n  ],\n  \"embedding\": [";
                for (size_t i = 0; i < embedding.size(); ++i) json << (i ? ", " : "") << embedding[i];
                json << "],\n  \"timings_ms\": {\"cpu\": " << cpu_ms << ", \"ai\": " << ai_ms << "}\n}\n";
                save(destination / "result.json", json.str());
                results.push_back({images[index], directory, std::move(embedding)});
                std::cout << images[index].filename().string() << " -> " << destination.string()
                          << " (CPU " << int(cpu_ms) << " ms, AI " << int(ai_ms) << " ms)\n";
            } catch (const std::exception& e) {
                ++failures;
                std::cerr << images[index].string() << ": " << e.what() << '\n';
            }
        }
        std::ostringstream summary;
        summary << std::setprecision(9) << "{\n  \"model_id\": " << quote(museboard::model_id)
                << ",\n  \"model_load_ms\": " << model_ms << ",\n  \"failed_images\": " << failures << ",\n  \"results\": [";
        for (size_t i = 0; i < results.size(); ++i) {
            std::vector<std::pair<double, size_t>> matches;
            for (size_t j = 0; j < results.size(); ++j)
                if (i != j && results[i].input != results[j].input)
                    matches.emplace_back(museboard::cosine(results[i].embedding, results[j].embedding), j);
            std::stable_sort(matches.begin(), matches.end(), [](auto a, auto b) { return a.first > b.first; });
            summary << (i ? "," : "") << "\n    {\"source\": " << quote(results[i].input.string())
                    << ", \"result\": " << quote(results[i].directory + "/result.json") << ", \"matches\": [";
            for (size_t j = 0; j < matches.size(); ++j) {
                const auto [score, target] = matches[j];
                summary << (j ? ", " : "") << "{\"source\": " << quote(results[target].input.string())
                        << ", \"cosine_similarity\": " << score << "}";
            }
            summary << "]}";
        }
        summary << "\n  ]\n}\n";
        save(output / "summary.json", summary.str());
        return failures ? 1 : 0;
    } catch (const std::exception& e) {
        std::cerr << "Error: " << e.what() << '\n';
        return 1;
    }
}
