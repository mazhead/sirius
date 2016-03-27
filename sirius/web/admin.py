import io
from PIL import Image
import flask
from flask.ext import login

from sirius.protocol import protocol_loop
from sirius.protocol import messages
from sirius.coding import image_encoding
from sirius.models import hardware

blueprint = flask.Blueprint('admin', __name__)

def gentemplate(instr):
    tmpl = '''\
    <p>{0}</p>
    <style>
   p{{
            font-weight:700;
            font-size:70px;
            text-transform:uppercase;
            line-height:1;
            font-family: Arial;
            width:385px;
    }}
    </style>
    '''.format(instr)
    return tmpl

@blueprint.route('/admin', methods=['GET'])
def admin_landing():
    return flask.render_template(
        'admin.html',
    )

@blueprint.route('/admin/randomly-change-personality', methods=['POST'])
def randomly_change_personality():

    printer = hardware.Printer.query.get(1)

    im = image_encoding.threshold(Image.open('./tests/normalface.png'))

    msg = messages.SetPersonalityWithMessage(
        device_address=printer.device_address,
        face_pixels=im,
        nothing_to_print_pixels=image_encoding.default_pipeline(gentemplate('Nothing to print')),
        cannot_see_bridge_pixels=image_encoding.default_pipeline(gentemplate('Cannot see bridge')),
        cannot_see_internet_pixels=image_encoding.default_pipeline(gentemplate('Cannot see internet')),
        message_pixels=image_encoding.default_pipeline(gentemplate('Hi there!')),
    )
    success, next_print_id = protocol_loop.send_message(
        printer.device_address, msg)

    if success:
        flask.flash('Sent your message to the printer!')
    else:
        flask.flash(("Could not send message because the "
                     "printer {} is offline.").format(printer.device_address),
                    'error')

    return flask.redirect('/admin')
