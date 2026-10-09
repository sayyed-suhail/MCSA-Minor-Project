from flask import Flask, jsonify, request

app = Flask(__name__)

services = {}


@app.route("/register", methods=["POST"])
def register_service():
    data = request.get_json(silent=True) or {}

    name = data.get("name")
    url = data.get("url")

    if not name or not url:
        return jsonify({
            "error": "name and url are required"
        }), 400

    services[name] = url

    print(f"Registered service: {name} -> {url}")

    return jsonify({
        "message": "Service registered successfully",
        "name": name,
        "url": url
    }), 200


@app.route("/discover/<name>", methods=["GET"])
def discover_service(name):
    if name not in services:
        return jsonify({
            "error": "Service not found"
        }), 404

    return jsonify({
        "url": services[name]
    }), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "service": "Service Registry",
        "status": "running"
    }), 200


if __name__ == "__main__":
    app.run(port=5000, debug=True)