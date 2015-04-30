# -*- coding: utf-8 -*-

import os
import sys
import types
from shutil import copy2

from django.utils import (six, translation)
from django.conf import settings
from django.conf.urls import include as include_urls
from django.http import HttpResponse
from django.test import RequestFactory
from django.core.urlresolvers import reverse
from django.core.management import call_command

from errors import (DistillError, DistillWarning)

class DistillRender(object):
    '''
        Renders a complete static site from all urls registered with
        distill_url() and then copies over all static media.
    '''

    def __init__(self, output_dir, urls_to_distill):
        self.output_dir = output_dir
        self.urls_to_distill = urls_to_distill
        # activate the default translation
        translation.activate(settings.LANGUAGE_CODE)

    def render(self):
        for distill_func, view_name, args, kwargs in self.urls_to_distill:
            for param_set in self.get_uri_values(distill_func):
                if self._is_str(param_set):
                    param_set = param_set,
                uri = self.generate_uri(view_name, param_set)
                render = self.render_view(uri, param_set, args)
                yield uri, render

    def _is_str(self, s):
        return isinstance(s, six.string_types)

    def get_uri_values(self, func):
        try:
            v = func()
        except Exception as e:
            trace = sys.exc_info()[2]
            raise DistillError('Failed to call distill function'), None, trace
        t = type(v)
        if t in (list, tuple):
            return v
        elif t == types.GeneratorType:
            return list(v)
        else:
            raise DistillError('Distill function returned an invalid type: {}'
                .format(t))

    def generate_uri(self, view_name, param_set):
        t = type(param_set)
        if t in (list, tuple):
            uri = reverse(view_name, args=param_set)
        elif t == dict:
            uri = reverse(view_name, kwargs=param_set)
        else:
            raise DistillError('Distill function returned an invalid type: {}'
                .format(t))
        return uri

    def render_view(self, uri, param_set, args):
        if len(args) < 2:
            raise DistillError('Invalid view arguments')
        view_regex, view_func = args[0], args[1]
        request_factory = RequestFactory()
        request = request_factory.get(uri)
        if type(param_set) == dict:
            a, k = (), param_set
        else:
            a, k = param_set, {}
        response = view_func(request, *a, **k)
        if self._is_str(response):
            response = HttpResponse(response)
        else:
            response.render()
        if response.status_code != 200:
            raise DistillError('View returned a non-200 status code: {}'
                .format(response.status_code))
        return response

    def copy_static(self, dir_from, dir_to):
        # we need to ignore some static dirs such as 'admin' so this is a little
        # more complex than a straight shutil.copytree()
        if not dir_from.endswith(os.sep):
            dir_from = dir_from + os.sep
        if not dir_to.endswith(os.sep):
            dir_to = dir_to + os.sep
        for root, dirs, files in os.walk(dir_from):
            dirs[:] = filter_dirs(dirs)
            for f in files:
                from_path = os.path.join(root, f)
                base_path = from_path[len(dir_from):]
                to_path = os.path.join(dir_to, base_path)
                to_path_dir = os.path.dirname(to_path)
                if not os.path.isdir(to_path_dir):
                    os.makedirs(to_path_dir)
                copy2(from_path, to_path)
                yield from_path, to_path

def run_collectstatic(stdout):
    stdout('Distill is running collectstatic...')
    call_command('collectstatic')
    stdout('')
    stdout('collectstatic complete, continuing...')

_ignore_dirs = ('admin', 'grappelli')
def filter_dirs(dirs):
    return [d for d in dirs if d not in _ignore_dirs]

def load_urls(stdout):
    stdout('Loading site URLs')
    site_urls = getattr(settings, 'ROOT_URLCONF')
    if site_urls:
        include_urls(site_urls)

def render_to_dir(output_dir, urls_to_distill, stdout):
    mimes = {}
    load_urls(stdout)
    renderer = DistillRender(output_dir, urls_to_distill)
    for page_uri, http_response in renderer.render():
        full_path = os.path.join(output_dir, page_uri[1:])
        content = http_response.content
        mime = http_response.get('Content-Type')
        stdout('Rendering page: {} -> {} ["{}", {} bytes]'.format(page_uri,
            full_path, mime, len(content)))
        with open(full_path, 'w') as f:
            f.write(content)
        mimes[full_path] = mime.split(';')[0].strip()
    static_url = settings.STATIC_URL
    static_url = static_url[1:] if static_url.startswith('/') else static_url
    static_output_dir = os.path.join(output_dir, static_url)
    for file_from, file_to in renderer.copy_static(settings.STATIC_ROOT,
        static_output_dir):
        stdout('Copying static: {} -> {}'.format(file_from, file_to))
    return mime

# eof