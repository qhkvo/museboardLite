#include "museboard/processing.hpp"
#include <cmath>
#include <iostream>
#include <stdexcept>

// Checks processing geometry, colors, tensor layout, and vector math.

void check(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
int main() {
    try {
        cv::Mat wide(300, 1000, CV_8UC3, cv::Scalar(0, 0, 255));
        const auto thumb = museboard::thumbnail(wide);
        check(thumb.cols == 512 && thumb.rows == 154, "Thumbnail aspect ratio");
        cv::Mat tiny(1, 1, CV_8UC3, cv::Scalar(0, 0, 255));
        check(museboard::thumbnail(tiny).cols == 1, "Do not upscale thumbnails");
        const auto colors = museboard::palette(tiny);
        check(colors.size() == 5 && colors.front().hex == "#FF0000", "Tiny image palette");
        double total = 0;
        for (const auto& color : colors) total += color.weight;
        check(std::abs(total - 1) < 1e-6, "Palette weights sum to one");
        cv::Mat bands(100, 100, CV_8UC3);
        const cv::Scalar swatches[] = {{0,0,255},{0,255,0},{255,0,0},{0,255,255},{255,0,255}};
        for (int i = 0; i < 5; ++i) bands.colRange(i * 20, (i + 1) * 20).setTo(swatches[i]);
        const auto band_colors = museboard::palette(bands);
        for (const auto& c : band_colors) check(std::abs(c.weight - 0.2) < 1e-5, "Balanced palette weights");
        const auto input = museboard::clip_input(wide);
        check(input.size() == 3 * 224 * 224, "CLIP input shape");
        check(std::abs(input[0] - (1.f - 0.48145466f) / 0.26862954f) < 1e-5, "RGB channel order and normalization");
        check(std::abs(input[224 * 224] - (0.f - 0.4578275f) / 0.26130258f) < 1e-5, "NCHW layout");
        std::vector<float> vector{3,4};
        museboard::normalize(vector);
        check(std::abs(vector[0] - 0.6) < 1e-6, "L2 normalization");
        check(std::abs(museboard::cosine(vector, vector) - 1) < 1e-6, "Self similarity");
        check(std::abs(museboard::cosine({1,0}, {0,1})) < 1e-6, "Orthogonal similarity");
        bool rejected = false;
        try { museboard::cosine({0,0}, {1,0}); } catch (const std::invalid_argument&) { rejected = true; }
        check(rejected, "Reject zero embedding");
        std::cout << "Processing checks passed\n";
        return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
