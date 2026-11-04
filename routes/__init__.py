def register_routes(app):
    from .accounts import bp as accounts_bp
    from .inbox import bp as inbox_bp
    from .inventory import bp as inventory_bp
    from .pickup import bp as pickup_bp
    from .scheduler import bp as scheduler_bp
    from .apple_login import bp as apple_login_bp

    for bp in (accounts_bp, inbox_bp, inventory_bp, pickup_bp, scheduler_bp, apple_login_bp):
        app.register_blueprint(bp)
    return app
