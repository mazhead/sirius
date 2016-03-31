# -*- coding: utf-8 -*-
# encoding: utf-8
import os
import glob
import io
import datetime
import flask
from flask.ext import login
import flask_wtf
import wtforms
import base64

from flask import Flask, request, redirect, url_for

from io import BytesIO
from sirius.models.db import db
from sirius.models import hardware
from sirius.models import messages as model_messages
from sirius.protocol import protocol_loop
from sirius.protocol import messages
from sirius.coding import image_encoding
from sirius.coding import templating
from sirius import stats
from sirius import config
from werkzeug import secure_filename

ALLOWED_EXTENSIONS = set(['png', 'jpg', 'jpeg', 'gif'])

app = Flask(__name__)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1] in ALLOWED_EXTENSIONS

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

blueprint = flask.Blueprint('printer_print', __name__)

class PrintForm(flask_wtf.Form):
    target_printer = wtforms.SelectField(
        'Printer',
        coerce=int,
        validators=[wtforms.validators.DataRequired()],
    )
    message = wtforms.TextAreaField(
        'Message (optional)',
        validators=[wtforms.validators.DataRequired()],
    )
    photo = wtforms.FileField('Image')


@login.login_required
@blueprint.route('/printer/<int:printer_id>/print', methods=['GET', 'POST'])
def printer_print(printer_id):
    printer = hardware.Printer.query.get(printer_id)
    if printer is None:
        flask.abort(404)

    # PERMISSIONS
    # the printer must either belong to this user, or be
    # owned by a friend
    if printer.owner.id == login.current_user.id:
        # fine
        pass
    elif printer.id in [p.id for p in login.current_user.friends_printers()]:
        # fine
        pass
    else:
        flask.abort(404)

    form = PrintForm()
    # Note that the form enforces access permissions: People can't
    # submit a valid printer-id that's not owned by the user or one of
    # the user's friends.
    choices = [
        (x.id, x.name) for x in login.current_user.printers
    ] + [
        (x.id, x.name) for x in login.current_user.friends_printers()
    ]
    form.target_printer.choices = choices

    # Set default printer on get
    if flask.request.method != 'POST':
        form.target_printer.data = printer.id

    if form.validate_on_submit():
        # TODO: move image encoding into a pthread.
        # TODO: use templating to avoid injection attacks
        pixels = image_encoding.default_pipeline(
            templating.default_template(form.message.data))
        hardware_message = messages.SetDeliveryAndPrint(
            device_address=printer.device_address,
            pixels=pixels,
        )

        # If a printer is "offline" then we won't find the printer
        # connected and success will be false.
        success, next_print_id = protocol_loop.send_message(
            printer.device_address, hardware_message)

        if success:
            flask.flash('Sent your message to the printer!')
            stats.inc('printer.print.ok')
        else:
            flask.flash(("Could not send message because the "
                         "printer {} is offline.").format(printer.name),
                        'error')
            stats.inc('printer.print.offline')

        # Store the same message in the database.
        png = io.BytesIO()
        pixels.save(png, "PNG")
        model_message = model_messages.Message(
            print_id=next_print_id,
            pixels=bytearray(png.getvalue()),
            sender_id=login.current_user.id,
            target_printer=printer,
        )

        # We know immediately if the printer wasn't online.
        if not success:
            model_message.failure_message = 'Printer offline'
            model_message.response_timestamp = datetime.datetime.utcnow()
        db.session.add(model_message)

        return flask.redirect(flask.url_for(
            'printer_overview.printer_overview',
            printer_id=printer.id))

    return flask.render_template(
        'printer_print.html',
        printer=printer,
        form=form,
    )


@login.login_required
@blueprint.route('/printer/<int:printer_id>/printimage', methods=['GET', 'POST'])
def imageprint(printer_id):
    printer = hardware.Printer.query.get(printer_id)
    if printer is None:
        flask.abort(404)
    form = PrintForm()
    if flask.request.method == 'POST':
        pixels = image_encoding.image_pipeline(max(glob.iglob('/var/upload/*'), key=os.path.getctime))
        ##################
        hardware_message = messages.SetDeliveryAndPrint(
            device_address=printer.device_address,
            pixels=pixels,
        )

        # If a printer is "offline" then we won't find the printer
        # connected and success will be false.
        success, next_print_id = protocol_loop.send_message(
            printer.device_address, hardware_message)

        if success:
            flask.flash('Sent your message to the printer!')
            stats.inc('printer.print.ok')
        else:
            flask.flash(("Could not send message because the "
                         "printer {} is offline.").format(printer.name),
                        'error')
            stats.inc('printer.print.offline')

        # Store the same message in the database.
        png = io.BytesIO()
        pixels.save(png, "PNG")
        model_message = model_messages.Message(
            print_id=next_print_id,
            pixels=bytearray(png.getvalue()),
            sender_id=login.current_user.id,
            target_printer=printer,
        )

        # We know immediately if the printer wasn't online.
        if not success:
            model_message.failure_message = 'Printer offline'
            model_message.response_timestamp = datetime.datetime.utcnow()
        db.session.add(model_message)

        return flask.redirect(flask.url_for(
            'printer_overview.printer_overview',
            printer_id=printer.id))

    return flask.render_template(
        'printer_print_file.html',
        printer=printer,
        form=form
    )

@blueprint.route('/upload', methods=['GET','POST'])
def upload_file():
    file = flask.request.files['image']
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file.save(os.path.join('/var/upload/', filename))
        return filename

@blueprint.route('/<int:user_id>/<username>/printer/<int:printer_id>/preview', methods=['POST'])
@login.login_required
def preview(user_id, username, printer_id):
    assert user_id == login.current_user.id
    assert username == login.current_user.username

    message = flask.request.data.decode('utf-8')
    pixels = image_encoding.default_pipeline(
        templating.default_template(message))
    png = io.BytesIO()
    pixels.save(png, "PNG")

    stats.inc('printer.preview')

    return '<img style="width: 100%;" src="data:image/png;base64,{}">'.format(base64.b64encode(png.getvalue()))

#############API
#
#raw_image_pipeline

@blueprint.route('/printer/<action>/print_raw', methods=['POST'])
def raw_printer_print_api(action):
    # SetDeliveryAndPrint
    # SetDelivery
    # SetDeliveryAndPrintNoFace
    # SetDeliveryNoFace
    printer = hardware.Printer.query.get(1)
    pixels = image_encoding.raw_image_pipeline(BytesIO(base64.b64decode(flask.request.data)))
    print action
    if action == 'deliveryandface':
        hardware_message = messages.SetDelivery(
            device_address=printer.device_address,
            pixels=pixels,
        )
    elif action == 'printandface':
        hardware_message = messages.SetDeliveryAndPrint(
            device_address=printer.device_address,
            pixels=pixels,
        )
    elif action == 'delivery':
        hardware_message = messages.SetDeliveryNoFace(
            device_address=printer.device_address,
            pixels=pixels,
        )
    elif action == 'print':
        hardware_message = messages.SetDeliveryAndPrintNoFace(
            device_address=printer.device_address,
            pixels=pixels,
        )    
    elif action == 'print':
        hardware_message = messages.SetDeliveryAndPrintNoFace(
            device_address=printer.device_address,
            pixels=pixels,
        )   
    elif action == 'personalityandmessage':
        hardware_message = messages.SetPersonalityWithMessage(
            device_address=printer.device_address,
            face_pixels=pixels,
            nothing_to_print_pixels=image_encoding.default_pipeline(gentemplate('Nothing to print')),
            cannot_see_bridge_pixels=image_encoding.default_pipeline(gentemplate('Cannot see bridge')),
            cannot_see_internet_pixels=image_encoding.default_pipeline(gentemplate('Cannot see internet')),
            message_pixels=image_encoding.default_pipeline(gentemplate('Hi there!')),
        )   
    elif action == 'personality':
        hardware_message = messages.SetPersonality(
            device_address=printer.device_address,
            face_pixels=pixels,
            nothing_to_print_pixels=image_encoding.default_pipeline(gentemplate('Nothing to print')),
            cannot_see_bridge_pixels=image_encoding.default_pipeline(gentemplate('Cannot see bridge')),
            cannot_see_internet_pixels=image_encoding.default_pipeline(gentemplate('Cannot see internet'))
        )
    else:
        assert False, "wtf print route {}".format(x)

    # If a printer is "offline" then we won't find the printer
    # connected and success will be false.
    success, next_print_id = protocol_loop.send_message(
        printer.device_address, hardware_message)

    return 'ok'

@blueprint.route('/printer/print', methods=['POST'])
def printer_print_api():
    printer = hardware.Printer.query.get(1)
    pixels = image_encoding.default_pipeline(
        templating.default_template(flask.request.data))
    hardware_message = messages.SetDeliveryAndPrint(
        device_address=printer.device_address,
        pixels=pixels,
    )

    # If a printer is "offline" then we won't find the printer
    # connected and success will be false.
    success, next_print_id = protocol_loop.send_message(
        printer.device_address, hardware_message)

    if success:
        flask.flash('Sent your message to the printer!')
        stats.inc('printer.print.ok')
    else:
        flask.flash(("Could not send message because the "
                     "printer {} is offline.").format(printer.name),
                    'error')
        stats.inc('printer.print.offline')

    # We know immediately if the printer wasn't online.
    if not success:
        model_message.failure_message = 'Printer offline'
        model_message.response_timestamp = datetime.datetime.utcnow()
    db.session.add(model_message)

    return 'ok'


@blueprint.route('/printer/preview', methods=['POST'])
def preview_api():
    message = flask.request.data.decode('utf-8')
    pixels = image_encoding.default_pipeline(
        templating.default_template(message))
    png = io.BytesIO()
    pixels.save(png, "PNG")

    stats.inc('printer.preview')

    return '<img style="width: 100%;" src="data:image/png;base64,{}">'.format(base64.b64encode(png.getvalue()))
