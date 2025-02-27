"""
Various utilities for loading JS dependencies and rendering plots
inside the Jupyter notebook.
"""
from __future__ import absolute_import, division, unicode_literals

import json
import os
import uuid

from contextlib import contextmanager
from six import string_types

import bokeh
import bokeh.embed.notebook

from bokeh.core.templates import DOC_NB_JS
from bokeh.core.json_encoder import serialize_json
from bokeh.core.templates import MACROS
from bokeh.document import Document
from bokeh.embed import server_document
from bokeh.embed.bundle import bundle_for_objs_and_resources
from bokeh.embed.elements import div_for_render_item, script_for_render_items
from bokeh.embed.util import standalone_docs_json_and_render_items
from bokeh.embed.wrappers import wrap_in_script_tag
from bokeh.models import CustomJS, LayoutDOM, Model
from bokeh.resources import CDN, INLINE
from bokeh.util.string import encode_utf8, escape
from bokeh.util.serialization import make_id
from jinja2 import Environment, Markup, FileSystemLoader
from pyviz_comms import (
    JS_CALLBACK, PYVIZ_PROXY, Comm, JupyterCommManager as _JupyterCommManager,
    nb_mime_js)

from ..compiler import require_components
from .embed import embed_state
from .model import add_to_doc, diff
from .server import _server_url, _origin_url, get_server
from .state import state


#---------------------------------------------------------------------
# Private API
#---------------------------------------------------------------------

LOAD_MIME = 'application/vnd.holoviews_load.v0+json'
EXEC_MIME = 'application/vnd.holoviews_exec.v0+json'
HTML_MIME = 'text/html'

ABORT_JS = """
if (!window.PyViz) {{
  return;
}}
var events = [];
var receiver = window.PyViz.receivers['{plot_id}'];
if (receiver &&
        receiver._partial &&
        receiver._partial.content &&
        receiver._partial.content.events) {{
    events = receiver._partial.content.events;
}}

for (var event of events) {{
  if ((event.kind === 'ModelChanged') && (event.attr === '{change}') &&
      (cb_obj.id === event.model.id) &&
      (JSON.stringify(cb_obj['{change}']) === JSON.stringify(event.new))) {{
    events.pop(events.indexOf(event))
    return;
  }}
}}
"""

# Following JS block becomes body of the message handler callback
bokeh_msg_handler = """
var plot_id = "{plot_id}";

if ((plot_id in window.PyViz.plot_index) && (window.PyViz.plot_index[plot_id] != null)) {{
  var plot = window.PyViz.plot_index[plot_id];
}} else if ((Bokeh !== undefined) && (plot_id in Bokeh.index)) {{
  var plot = Bokeh.index[plot_id];
}}

if (plot == null) {{
  return
}}

if (plot_id in window.PyViz.receivers) {{
  var receiver = window.PyViz.receivers[plot_id];
}} else {{
  var receiver = new Bokeh.protocol.Receiver();
  window.PyViz.receivers[plot_id] = receiver;
}}

if ((buffers != undefined) && (buffers.length > 0)) {{
  receiver.consume(buffers[0].buffer)
}} else {{
  receiver.consume(msg)
}}

const comm_msg = receiver.message;
if ((comm_msg != null) && (Object.keys(comm_msg.content).length > 0)) {{
  plot.model.document.apply_json_patch(comm_msg.content, comm_msg.buffers)
}}
"""

def get_comm_customjs(change, client_comm, plot_id, timeout=5000, debounce=50):
    """
    Returns a CustomJS callback that can be attached to send the
    model state across the notebook comms.
    """
    # Abort callback if value matches last received event
    abort = ABORT_JS.format(plot_id=plot_id, change=change)
    data_template = """\
data = {{{change}: cb_obj['{change}'], 'id': cb_obj.id}};
cb_obj.event_name = '{change}';"""

    fetch_data = data_template.format(change=change)
    self_callback = JS_CALLBACK.format(
        comm_id=client_comm.id, timeout=timeout, debounce=debounce,
        plot_id=plot_id)
    return CustomJS(code='\n'.join([abort, fetch_data, self_callback]))



def push(doc, comm, binary=True):
    """
    Pushes events stored on the document across the provided comm.
    """
    msg = diff(doc, binary=binary)
    if msg is None:
        return
    comm.send(msg.header_json)
    comm.send(msg.metadata_json)
    comm.send(msg.content_json)
    for header, payload in msg.buffers:
        comm.send(json.dumps(header))
        comm.send(buffers=[payload])


def get_env():
    ''' Get the correct Jinja2 Environment, also for frozen scripts.
    '''
    local_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '_templates'))
    return Environment(loader=FileSystemLoader(local_path))

_env = get_env()
_env.filters['json'] = lambda obj: Markup(json.dumps(obj))
AUTOLOAD_NB_JS = _env.get_template("autoload_panel_js.js")
NB_TEMPLATE_BASE = _env.get_template('nb_template.html')

def _autoload_js(bundle, configs, requirements, exports, load_timeout=5000):
    return AUTOLOAD_NB_JS.render(
        bundle    = bundle,
        force     = True,
        timeout   = load_timeout,
        configs   = configs,
        requirements = requirements,
        exports   = exports
    )


def html_for_render_items(comm_js, docs_json, render_items, template=None, template_variables={}):
    comm_js = wrap_in_script_tag(comm_js)

    json_id = make_id()
    json = escape(serialize_json(docs_json), quote=False)
    json = wrap_in_script_tag(json, "application/json", json_id)

    script = wrap_in_script_tag(script_for_render_items(json_id, render_items))

    context = template_variables.copy()

    context.update(dict(
        title = '',
        bokeh_js = comm_js,
        plot_script = json + script,
        docs = render_items,
        base = NB_TEMPLATE_BASE,
        macros = MACROS,
    ))

    if len(render_items) == 1:
        context["doc"] = context["docs"][0]
        context["roots"] = context["doc"].roots

    if template is None:
        template = NB_TEMPLATE_BASE
    elif isinstance(template, string_types):
        template = _env.from_string("{% extends base %}\n" + template)

    html = template.render(context)
    return encode_utf8(html)


def render_template(document, comm=None):
    plot_id = document.roots[0].ref['id']
    (docs_json, render_items) = standalone_docs_json_and_render_items(document)

    if comm:
        msg_handler = bokeh_msg_handler.format(plot_id=plot_id)
        comm_js = comm.js_template.format(plot_id=plot_id, comm_id=comm.id, msg_handler=msg_handler)
    else:
        comm_js = ''

    html = html_for_render_items(
        comm_js, docs_json, render_items, template=document.template,
        template_variables=document.template_variables)

    return ({'text/html': html, EXEC_MIME: ''},
            {EXEC_MIME: {'id': plot_id}})


def render_model(model, comm=None):
    if not isinstance(model, Model):
        raise ValueError("notebook_content expects a single Model instance")

    target = model.ref['id']

    (docs_json, [render_item]) = standalone_docs_json_and_render_items([model])
    div = div_for_render_item(render_item)
    render_item = render_item.to_json()
    script = DOC_NB_JS.render(
        docs_json=serialize_json(docs_json),
        render_items=serialize_json([render_item]),
    )
    bokeh_script, bokeh_div = encode_utf8(script), encode_utf8(div)
    html = "<div id='{id}'>{html}</div>".format(id=target, html=bokeh_div)

    # Publish bokeh plot JS
    msg_handler = bokeh_msg_handler.format(plot_id=target)

    if comm:
        comm_js = comm.js_template.format(plot_id=target, comm_id=comm.id, msg_handler=msg_handler)
        bokeh_js = '\n'.join([comm_js, bokeh_script])
    else:
        bokeh_js = bokeh_script

    data = {'text/html': html, 'application/javascript': bokeh_js}
    return ({'text/html': mimebundle_to_html(data), EXEC_MIME: ''},
            {EXEC_MIME: {'id': target}})


def render_mimebundle(model, doc, comm):
    """
    Displays bokeh output inside a notebook using the PyViz display
    and comms machinery.
    """
    if not isinstance(model, LayoutDOM):
        raise ValueError('Can only render bokeh LayoutDOM models')
    add_to_doc(model, doc, True)
    return render_model(model, comm)


def mimebundle_to_html(bundle):
    """
    Converts a MIME bundle into HTML.
    """
    if isinstance(bundle, tuple):
        data, metadata = bundle
    else:
        data = bundle
    html = data.get('text/html', '')
    if 'application/javascript' in data:
        js = data['application/javascript']
        html += '\n<script type="application/javascript">{js}</script>'.format(js=js)
    return html

#---------------------------------------------------------------------
# Public API
#---------------------------------------------------------------------


@contextmanager
def block_comm():
    """
    Context manager to temporarily block comm push
    """
    state._hold = True
    yield
    state._hold = False


def load_notebook(inline=True, load_timeout=5000):
    from IPython.display import publish_display_data

    resources = INLINE if inline else CDN
    bundle = bundle_for_objs_and_resources(None, resources)
    configs, requirements, exports = require_components()

    bokeh_js = _autoload_js(bundle, configs, requirements, exports, load_timeout)
    publish_display_data({
        'application/javascript': bokeh_js,
        LOAD_MIME: bokeh_js,
    })
    bokeh.io.notebook.curstate().output_notebook()

    # Publish comm manager
    JS = '\n'.join([PYVIZ_PROXY, _JupyterCommManager.js_manager, nb_mime_js])
    publish_display_data(data={LOAD_MIME: JS, 'application/javascript': JS})


def show_server(panel, notebook_url, port):
    """
    Displays a bokeh server inline in the notebook.

    Arguments
    ---------
    panel: Viewable
      Panel Viewable object to launch a server for
    notebook_url: str
      The URL of the running Jupyter notebook server
    port: int (optional, default=0)
      Allows specifying a specific port
    server_id: str
      Unique ID to identify the server with

    Returns
    -------
    server: bokeh.server.Server
    """
    from IPython.display import publish_display_data

    if callable(notebook_url):
        origin = notebook_url(None)
    else:
        origin = _origin_url(notebook_url)
    server_id = uuid.uuid4().hex
    server = get_server(panel, port, origin, start=True, show=False,
                        server_id=server_id)

    if callable(notebook_url):
        url = notebook_url(server.port)
    else:
        url = _server_url(notebook_url, server.port)

    script = server_document(url, resources=None)

    publish_display_data({
        HTML_MIME: script,
        EXEC_MIME: ""
    }, metadata={
        EXEC_MIME: {"server_id": server_id}
    })
    return server


def show_embed(panel, max_states=1000, max_opts=3, json=False,
              save_path='./', load_path=None):
    """
    Renders a static version of a panel in a notebook by evaluating
    the set of states defined by the widgets in the model. Note
    this will only work well for simple apps with a relatively
    small state space.

    Arguments
    ---------
    max_states: int
      The maximum number of states to embed
    max_opts: int
      The maximum number of states for a single widget
    json: boolean (default=True)
      Whether to export the data to json files
    save_path: str (default='./')
      The path to save json files to
    load_path: str (default=None)
      The path or URL the json files will be loaded from.
    """
    from IPython.display import publish_display_data
    from ..config import config

    doc = Document()
    comm = Comm()
    with config.set(embed=True):
        model = panel.get_root(doc, comm)
        embed_state(panel, model, doc, max_states, max_opts,
                    json, save_path, load_path)
    publish_display_data(*render_model(model))


def ipywidget(panel):
    """
    Creates a root model from the Panel object and wraps it in
    a jupyter_bokeh ipywidget BokehModel.

    Returns
    -------
    Returns an ipywidget model which renders the Panel object.
    """
    from jupyter_bokeh import BokehModel
    return BokehModel(panel.get_root())
