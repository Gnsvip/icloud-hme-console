from flask import Blueprint, jsonify, request

from app_core import _account_mgr
from services.apple_login_service import AppleLoginManager, LoginError

bp = Blueprint("apple_login", __name__)
manager = AppleLoginManager(_account_mgr)


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise LoginError("请求内容格式不正确。")
    return data


@bp.errorhandler(LoginError)
def login_error(error):
    return jsonify({"ok": False, "error": str(error)}), error.status


@bp.route("/api/apple-login", methods=["POST"])
def start():
    return jsonify(manager.start(body())), 202


@bp.route("/api/apple-login/<flow_id>", methods=["GET", "DELETE"])
def status(flow_id):
    return jsonify(manager.cancel(flow_id) if request.method == "DELETE" else manager.status(flow_id))


@bp.route("/api/apple-login/<flow_id>/verify", methods=["POST"])
def verify(flow_id):
    return jsonify(manager.verify(flow_id, body().get("code"))), 202


@bp.route("/api/apple-login/<flow_id>/resume", methods=["POST"])
def resume(flow_id):
    return jsonify(manager.resume(flow_id)), 202
