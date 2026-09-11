#pragma once
#include <opencv2/core.hpp>
#include <filesystem>
#include <string>
#include <vector>

// Image decoding, orientation, thumbnails, palettes, CLIP preprocessing, and vector math.

namespace museboard {
struct PaletteColor {
    std::string hex;
    cv::Vec3f lab;
    double weight;
};
cv::Mat load_image(const std::filesystem::path& path);
cv::Mat thumbnail(const cv::Mat& bgr, int max_edge = 512);
std::vector<PaletteColor> palette(const cv::Mat& bgr);
std::vector<float> clip_input(const cv::Mat& bgr);
void normalize(std::vector<float>& values);
double cosine(const std::vector<float>& a, const std::vector<float>& b);
}
