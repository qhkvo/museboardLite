#include "museboard/encoder.hpp"
#include "museboard/processing.hpp"
#include <curl/curl.h>
#include <opencv2/imgcodecs.hpp>
#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <thread>

namespace fs = std::filesystem;
static volatile std::sig_atomic_t stopping = 0;
static void stop(int) { stopping = 1; }
static std::string env(const char* key, const char* fallback) {
    const char* value = std::getenv(key);
    return value ? value : fallback;
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

struct Response { long status; std::string body; };
static size_t receive(char* data, size_t size, size_t count, void* target) {
    auto& body = *static_cast<std::string*>(target);
    const auto bytes = size * count;
    if (body.size() + bytes > 64 * 1024) return 0;
    body.append(data, bytes);
    return bytes;
}

class Client {
    std::string base_, credential_;
public:
    Client(std::string base, std::string token) : base_(std::move(base)), credential_("Authorization: Bearer " + token) {
        if (token.empty() || token.find_first_of("\r\n") != std::string::npos)
            throw std::invalid_argument("Set WORKER_TOKEN to the API worker credential");
        if (!base_.starts_with("http://") && !base_.starts_with("https://"))
            throw std::invalid_argument("API_URL must use http or https");
        while (base_.ends_with('/')) base_.pop_back();
    }
    Response post(const std::string& path, const std::string& json) {
        std::unique_ptr<CURL, decltype(&curl_easy_cleanup)> curl(curl_easy_init(), curl_easy_cleanup);
        if (!curl) throw std::runtime_error("Cannot initialize HTTP client");
        curl_slist* raw = nullptr;
        raw = curl_slist_append(raw, "Content-Type: application/json");
        raw = curl_slist_append(raw, credential_.c_str());
        std::unique_ptr<curl_slist, decltype(&curl_slist_free_all)> headers(raw, curl_slist_free_all);
        Response response{};
        const auto url = base_ + path;
        curl_easy_setopt(curl.get(), CURLOPT_URL, url.c_str());
        curl_easy_setopt(curl.get(), CURLOPT_HTTPHEADER, headers.get());
        curl_easy_setopt(curl.get(), CURLOPT_POSTFIELDS, json.c_str());
        curl_easy_setopt(curl.get(), CURLOPT_POSTFIELDSIZE, static_cast<long>(json.size()));
        curl_easy_setopt(curl.get(), CURLOPT_CONNECTTIMEOUT, 5L);
        curl_easy_setopt(curl.get(), CURLOPT_TIMEOUT, 30L);
        curl_easy_setopt(curl.get(), CURLOPT_NOSIGNAL, 1L);
        curl_easy_setopt(curl.get(), CURLOPT_WRITEFUNCTION, receive);
        curl_easy_setopt(curl.get(), CURLOPT_WRITEDATA, &response.body);
        const auto result = curl_easy_perform(curl.get());
        if (result != CURLE_OK) throw std::runtime_error(std::string("HTTP transport: ") + curl_easy_strerror(result));
        curl_easy_getinfo(curl.get(), CURLINFO_RESPONSE_CODE, &response.status);
        return response;
    }
};

// The API supplies generated relative paths. Resolve symlinks as well as '..'.
static fs::path storage_path(const fs::path& root, const std::string& value, const std::string& area) {
    fs::path relative(value);
    if (relative.is_absolute() || relative.empty() || *relative.begin() != area)
        throw std::runtime_error("Invalid storage path");
    auto path = fs::weakly_canonical(root / relative);
    auto allowed = fs::weakly_canonical(root / area);
    auto under = path.lexically_relative(allowed);
    if (under.empty() || under.is_absolute() || *under.begin() == "..")
        throw std::runtime_error("Storage path escapes its directory");
    return path;
}

static std::string field(const cv::FileStorage& json, const char* name) {
    auto node = json[name];
    if (!node.isString() || node.string().empty()) throw std::runtime_error(std::string("Invalid claim field: ") + name);
    return node.string();
}

static void idle() {
    for (int i=0; i<20 && !stopping; ++i) std::this_thread::sleep_for(std::chrono::milliseconds(100));
}

int main(int argc, char** argv) {
    try {
        std::string mode;
        bool once = false;
        fs::path model = env("MODEL_PATH", "models/vision_model.onnx");

        for (int i=1; i<argc; ++i) {
            std::string arg = argv[i];
            if (arg == "--help") {
                std::cout << "Usage: museboard-worker --mode cpu|ai [--model MODEL.onnx] [--once]\n"
                             "Environment: API_URL, WORKER_TOKEN (required), STORAGE_DIR, MODEL_PATH\n"
                             "--once claims at most one job; otherwise polls until SIGINT/SIGTERM.\n";
                return 0;
            }
            if (arg == "--once") { once = true; continue; }
            if ((arg == "--mode" || arg == "--model") && i+1 < argc) {
                if (arg == "--mode") mode = argv[++i]; else model = argv[++i];
            } else throw std::invalid_argument("Unknown or incomplete option: " + arg);
        }

        if (mode != "cpu" && mode != "ai") throw std::invalid_argument("--mode must be cpu or ai");

        const auto root = fs::weakly_canonical(env("STORAGE_DIR", "./data"));

        setenv("OPENCV_IO_MAX_IMAGE_PIXELS", "40000000", 0);
        setenv("OPENCV_IO_MAX_IMAGE_WIDTH", "16384", 0);
        setenv("OPENCV_IO_MAX_IMAGE_HEIGHT", "16384", 0);

        cv::setNumThreads(2);

        if (curl_global_init(CURL_GLOBAL_DEFAULT) != CURLE_OK) throw std::runtime_error("Cannot initialize curl");

        struct Cleanup { ~Cleanup() { curl_global_cleanup(); } } cleanup;
        Client client(env("API_URL", "http://127.0.0.1:8000"), env("WORKER_TOKEN", ""));

        // CPU processes do not load a model. AI processes reuse one session.
        std::unique_ptr<museboard::Encoder> encoder;

        if (mode == "ai") encoder = std::make_unique<museboard::Encoder>(model);

        std::signal(SIGINT, stop);
        std::signal(SIGTERM, stop);

        const std::string type = mode == "cpu" ? "cpu_process" : "ai_embed";

        while (!stopping) {
            try {
                auto response = client.post("/internal/jobs/claim", "{\"type\":" + quote(type) + "}");
                if (response.status == 204) { if (once) return 0; idle(); continue; }
                if (response.status == 401 || response.status == 403) throw std::invalid_argument("Worker credential rejected");
                if (response.status != 200) throw std::runtime_error("Claim HTTP " + std::to_string(response.status));

                cv::FileStorage job(response.body, cv::FileStorage::READ | cv::FileStorage::MEMORY | cv::FileStorage::FORMAT_JSON);

                const auto id = field(job, "id"), token = field(job, "attempt_token");
                const auto endpoint = "/internal/jobs/" + id;
                std::string payload;

                try {
                    const auto source = storage_path(root, field(job, "original_path"), "originals");
                    const auto image = museboard::load_image(source);
                    std::ostringstream json;
                    json << std::setprecision(9) << "{\"type\":" << quote(type) << ",\"attempt_token\":" << quote(token);

                    if (mode == "cpu") {
                        const auto relative = field(job, "thumbnail_path");
                        const auto destination = storage_path(root, relative, "thumbnails");
                        fs::create_directories(destination.parent_path());

                        // Write atomically within the attempt's directory. Another attempt always uses a different final filename.
                        const auto temporary = destination.parent_path() / (destination.stem().string() + ".tmp.jpg");
                        const auto colors = museboard::palette(image);

                        if (!cv::imwrite(temporary.string(), museboard::thumbnail(image))) throw std::runtime_error("Cannot write thumbnail");

                        fs::rename(temporary, destination);
                        json << ",\"thumbnail_path\":" << quote(relative) << ",\"palette\":[";

                        for (size_t i=0; i<colors.size(); ++i) {
                            const auto& c = colors[i];
                            json << (i ? "," : "") << "{\"hex\":" << quote(c.hex) << ",\"weight\":" << c.weight
                                 << ",\"lab\":[" << c.lab[0] << ',' << c.lab[1] << ',' << c.lab[2] << "]}";
                        }
                        json << ']';

                    } else {
                        const auto embedding = encoder->encode(image);
                        json << ",\"model_id\":" << quote(museboard::model_id) << ",\"embedding\":[";
                        for (size_t i=0; i<embedding.size(); ++i) json << (i ? "," : "") << embedding[i];
                        json << ']';
                    }

                    json << '}';
                    payload = json.str();

                } catch (const std::exception& e) {
                    const auto failure = client.post(endpoint + "/fail", "{\"attempt_token\":" + quote(token)
                        + ",\"error\":" + quote(std::string(e.what()).substr(0, 1800)) + ",\"retryable\":true}");
                    std::cerr << id << " processing failed; report HTTP " << failure.status << '\n';

                    if (once) return 1;
                    continue;
                }

                // On ambiguous transport failure, leave the lease alone: the API may have committed. Recovery retries only if it did not commit.
                response = client.post(endpoint + "/complete", payload);
                if (response.status == 409) std::cerr << id << " expired; result discarded\n";
                else if (response.status != 200) throw std::runtime_error("Completion HTTP " + std::to_string(response.status));
                else std::cout << id << " " << type << " succeeded" << std::endl;

                if (once) return response.status == 200 ? 0 : 1;

            } catch (const std::invalid_argument&) { throw; }

            catch (const std::exception& e) {
                std::cerr << e.what() << '\n';
                if (once) return 1;
                idle();
            }
        }
        return 0;
        
    } catch (const std::exception& e) {
        std::cerr << "Error: " << e.what() << '\n';
        return 1;
    }
}
