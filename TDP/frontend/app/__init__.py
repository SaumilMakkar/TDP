from flask import Flask
from config import Config

def create_app(config_class=Config):
    app = Flask(__name__, static_url_path='/static', static_folder='../static')
    app.config.from_object(config_class)

    # Register blueprints here
    from app.routes.main import main_bp
    from app.routes.auth import auth_bp
    from app.routes.prescription import prescription_bp
    from app.routes.provider import provider_bp
    from app.routes.review import review_bp
    from app.routes.pbm import pbm_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/api')
    app.register_blueprint(prescription_bp, url_prefix='/api')
    app.register_blueprint(provider_bp)
    app.register_blueprint(review_bp)
    app.register_blueprint(pbm_bp)

    return app
