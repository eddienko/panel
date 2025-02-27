# -*- coding: utf-8 -*-

from nbsite.shared_conf import *

project = u'Panel'
authors = u'Panel contributors'
copyright = u'2019 ' + authors
description = 'High-level dashboarding for python visualization libraries'

import panel
version = release = str(panel.__version__)

html_static_path += ['_static']
html_theme = 'sphinx_ioam_theme'
html_theme_options = {
    'logo': 'logo_horizontal.png',
    'favicon': 'favicon.ico',
    'css': 'site.css'    
}

extensions += ['nbsite.gallery']

nbsite_gallery_conf = {
    'github_org': 'pyviz',
    'github_project': 'panel',
    'galleries': {
        'gallery': {
            'title': 'Gallery',
            'sections': [
                {'path': 'demos',
                 'title': 'Demos',
                 'description': 'A set of sophisticated apps built to demonstrate the features of Panel.'},
                {'path': 'simple',
                 'title': 'Simple Apps',
                 'description': 'Simple example apps meant to provide a quick introduction to Panel.'},
                {'path': 'apis',
                 'title': 'APIs',
                 'description': ('Examples meant to demonstrate the usage of different Panel APIs '
                                 'such as interact and reactive functions.')},
                {'path': 'layout',
                 'title': 'Layouts',
                 'description': 'How to leverage Panel layout components to achieve complex layouts.'},
                {'path': 'dynamic',
                 'title': 'Dynamic UIs',
                 'description': ('Examples demonstrating how to build dynamic UIs with components that'
                                 'are added or removed interactively.')},
                {'path': 'param',
                 'title': 'Param based apps',
                 'description': 'Using the Param library to express UIs independently of Panel.'},
                {'path': 'links',
                 'title': 'Linking',
                 'description': ('Using Javascript based links to define interactivity without '
                                 'without requiring a live kernel.')},
                {'path': 'external',
                 'title': 'External libraries',
                 'description': 'Wrapping external libraries with Panel.'}
            ]
        },
        'reference': {
            'title': 'Reference Gallery',
            'sections': [
                'panes',
                'layouts',
                'widgets'
            ]
        }
    },
    'thumbnail_url': 'https://assets.holoviews.org/panel/thumbnails',
    'deployment_url': 'https://panel-gallery.pyviz.demo.anaconda.com/'
}

_NAV = (
    ('Getting started', 'getting_started/index'),
    ('User Guide', 'user_guide/index'),
    ('Gallery', 'gallery/index'),
    ('Reference Gallery', 'reference/index'),
    ('Developer Guide', 'developer_guide/index'),
    ('FAQ', 'FAQ'),
    ('About', 'about')
)

templates_path = ['_templates']

html_context.update({
    'PROJECT': project,
    'DESCRIPTION': description,
    'AUTHOR': authors,
    'VERSION': version,
    'WEBSITE_URL': 'https://panel.pyviz.org',
    'WEBSITE_SERVER': 'https://panel.pyviz.org',
    'NAV': _NAV,
    'LINKS': _NAV,
    'SOCIAL': (
        ('Gitter', '//gitter.im/pyviz/pyviz'),
        ('Github', '//github.com/pyviz/panel'),
    )
})

nbbuild_patterns_to_take_along = ["simple.html"]
