import io
import flask

blueprint = flask.Blueprint('atkinson', __name__ ,static_folder='static', static_url_path='/asset')


@blueprint.route('/atkinson', methods=['GET'])
def atkinson_page():
    return flask.render_template(
        'atkinson.html',
    )
