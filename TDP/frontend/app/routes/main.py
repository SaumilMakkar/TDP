from flask import Blueprint, render_template

from app.presenters.main_presenter import build_home_page_context

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    return render_template('pages/home.html', **build_home_page_context())
