from . import mkdir_p
from .item import load_item
from . import process
from .theme import Theme
from . import oembed
import argparse
import chirun
import datetime
import json
import logging
import os
from   pathlib import Path
import shutil
import yaml


logger = logging.getLogger('chirun')


class Chirun:

    mathjax_url = 'https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js'
    processor_classes = [
        process.SlugCollisionProcess,
        process.LastBuiltProcess,
        process.PDFProcess,
        process.NotebookProcess,
        process.RenderProcess
    ]

    def __init__(self, args):
        self.args = args
        self.force_relative_build = False
        self.force_theme = False

        self.root_dir = self.get_root_dir()
        self.build_dir = Path(args.build_path) if args.build_path is not None else self.root_dir / 'build'

        if args.veryverbose:
            args.verbose = True

        if args.verbose:
            if args.veryverbose:
                logger.setLevel(logging.DEBUG)
                logging.basicConfig(format='[%(name)s:%(funcName)s:%(lineno)d] %(message)s')
            else:
                logger.setLevel(logging.INFO)
                logging.basicConfig(format='%(message)s')

        TEXINPUTS = [os.path.dirname(os.path.realpath(chirun.__file__)), '']
        TEXINPUTS += [os.environ.get('TEXINPUTS', '')]
        os.environ['TEXINPUTS'] = ':'.join(TEXINPUTS)

    def get_root_dir(self):
        """
            The path to the course's source directory
        """
        return Path(self.args.dir)

    def get_build_dir(self):
        """
            The path the output will be put in
        """
        return self.build_dir / (self.force_theme.path if self.force_theme else self.theme.path)

    def get_static_dir(self):
        """
            The path to the course's static files source
        """
        return Path(self.config['static_dir'])

    def get_web_root(self):
        """
            The root URL of the course.
        """
        base = self.config.get('base_dir')
        code = self.config.get('code')
        year = self.config.get('year')
        theme_path = self.force_theme.path if self.force_theme else self.theme.path

        if 'root_url' not in self.config.keys():
            self.config['root_url'] = '/{base}/'
            if code:
                self.config['root_url'] += '{code}/'
            if len(self.config['themes']) > 1:
                self.config['root_url'] += '{theme}/'

        if not self.args.absolute or self.force_relative_build:
            return str(self.get_build_dir().resolve()) + '/'
        else:
            return self.config.get('root_url').format(base=base, code=code, year=year, theme=theme_path)

    def make_relative_url(self, item, url):
        """
            Make the URL relative to the item's location.

            If the 'absolute' option is turned on, the web root is instead added
            to the beginning of absolute URLs, when required.
        """
        root = self.get_web_root()
        if self.args.absolute:
            if url[:len(root) - 1] != root[1:]:
                url = root + url
            else:
                url = '/' + url
            return url
        else:
            levels = len(item.out_file.parents) - 1

            if url[:len(root) - 1] == root[1:]:
                url = url[len(root) - 1:]

            if self.force_theme:
                return '/'.join(['..'] * (levels + 1)) + '/' + self.force_theme.path + '/' + url
            elif levels > 0:
                return '/'.join(['..'] * levels) + '/' + url
            else:
                return url

    def default_config(self):
        root_dir = self.get_root_dir()
        config = {
            'static_dir': root_dir / 'static',
            'build_pdf': True,
            'num_pdf_runs': 1,
            'year': datetime.datetime.now().year,
            'format_version': 2,
            'mathjax_url': self.mathjax_url,
            'themes': [{
                'title': 'Default',
                'source': 'default',
                'path': '.'
            }]
        }
        return config

    def get_config_file(self):
        """
            The path to the config file
        """
        if self.args.config_file:
            return Path(self.args.config_file)
        else:
            return self.get_root_dir() / 'config.yml'

    def load_config(self):
        """
            Load the config.

            Extend the default config with the config loaded from the filesystem
        """

        self.config = self.default_config()

        config_file = self.get_config_file()

        logger.debug("Reading config file {}".format(config_file))

        if config_file.exists():
            with open(str(config_file), 'r') as f:
                try:
                    config = self.loaded_config = yaml.load(f, Loader=yaml.CLoader)
                except AttributeError:
                    config = self.loaded_config = yaml.load(f, Loader=yaml.Loader)
            self.config.update(self.loaded_config)

        else:
            if self.args.single_file is None:
                raise Exception(f"The config file {config_file} does not exist.")


        if self.args.single_file:
            self.config.update({
                'structure': [
                    {
                        'type': 'standalone',
                        'sidebar': False,
                        'topbar': False,
                        'footer': True,
                        'source': self.args.single_file
                    }
                ]
            })

        self.config['args'] = self.args

    def get_main_file(self):
        if self.args.single_file:
            return Path(self.args.single_file)
        else:
            return self.get_config_file()

    def theme_directories(self):
        """
            An iterator for paths containing themes

            Tries:
                * The themes_dir path specified in the config
                * The directory 'themes' under the root directory of the course
                * The directory 'themes' in the chirun package
                * The directory 'themes' in the current working directory
        """
        if 'themes_dir' in self.config:
            yield Path(self.config.get('themes_dir'))
        yield self.get_root_dir() / 'themes'
        yield Path(__file__).parent / 'themes'
        yield Path(chirun.__file__).parent / 'themes'
        yield Path('themes')

    def find_theme(self, name):
        """
            Find the source directory for the theme with the given name
        """
        logger.debug("Finding theme {}".format(name))
        for path in self.theme_directories():
            p = path / name
            logger.debug("Trying {}".format(p))
            if p.exists():
                return p

        raise Exception("Couldn't find theme {}".format(name))

    def load_themes(self):
        """
            Load every theme defined in the config
        """
        self.themes = []
        for theme_data in self.config['themes']:
            name = theme_data['source']
            source = self.find_theme(name)
            theme = Theme(self, name, source, theme_data)
            self.themes.append(theme)

    def copy_static_files(self):
        """
            Copy any files in the course's `static` directory to `build_dir/static`
        """
        logger.debug("Copying course's static directory to the build's static directory...")

        srcPath = self.get_static_dir()
        dstPath = self.get_build_dir() / 'static'
        if srcPath.is_dir():
            logger.debug("    {src} => {dest}".format(src=srcPath, dest=dstPath))
            try:
                shutil.copytree(str(srcPath), str(dstPath), dirs_exist_ok=True)
            except Exception:
                logger.warning("Warning: Problem copying Course's static directory!")

    def load_structure(self):
        """
            Load all the items defined in the config
        """
        logger.debug('Loading course structure')
        self.structure = [load_item(self, obj) for obj in self.config['structure']]

        # Ensure an item exists in the course structure to produce an index page.
        if not any(item.is_index for item in self.structure):
            index = {'type': 'introduction'}
            self.structure.append(load_item(self, index))

    def process(self):
        """
            Process the course.
            Each process visits all the items in the course structure and builds a different format.
        """
        logger.debug("Starting processing")

        processors = [p(self) for p in self.processor_classes]
        for processor in processors:
            logger.info("Process: " + processor.name)
            for n in range(processor.num_runs):
                if processor.num_runs > 1:
                    logger.info("Run {}/{}".format(n + 1, processor.num_runs))
                for item in self.structure:
                    processor.visit(item)

        logger.debug('Finished processing course items')

    def optimize(self):
        pass

    def temp_path(self, subpath=None):
        """
            Construct a temporary directory to do work in.
            Deleted at the end, in Chirun.cleanup.
        """
        path = Path('tmp') / self.theme.path

        if subpath:
            path = path / subpath

        mkdir_p(path)
        return path

    def cleanup(self):
        """
            Remove temporary files created during the build process
        """
        logger.info("Cleaning up temporary files")

        try:
            shutil.rmtree('tmp')
        except OSError:
            pass

    def get_context(self):
        """
            A dictionary of context information about the course, for templates to use
        """
        return {
            'author': self.config.get('author'),
            'institution': self.config.get('institution'),
            'code': self.config.get('code'),
            'year': self.config.get('year'),
            'theme': self.theme.get_context(),
            'alt_themes': self.theme.alt_themes_contexts(),
        }

    def make_directories(self):
        """
            Make the output directory
        """
        logger.debug("Creating build directory...")
        mkdir_p(self.get_build_dir())
        mkdir_p(self.get_build_dir() / 'static')

    def save_manifest(self):
        """
            Write out a manifest similar to config.yml, but
            including possible changes to the structure introduced
            by item types that dynamically create further content
            items.
        """
        manifest_path = self.build_dir / 'MANIFEST.yml'
        manifest = self.config
        manifest.update({'structure': [item.content_tree() for item in self.structure]})
        del manifest['args']
        del manifest['static_dir']
        with open(manifest_path, 'w') as f:
            yaml.dump(manifest, f)

        with open(manifest_path.with_suffix('.json'), 'w') as f:
            json.dump(manifest, f)

    def build_with_theme(self, theme):
        """
            Build the course using the given theme
        """
        self.theme = theme

        logger.debug("""
The static directory is: {static_dir}
The build directory is: {build_dir}
The web root directory is: {web_root}
""".format(
            static_dir=self.get_static_dir(),
            build_dir=self.get_build_dir(),
            web_root=self.get_web_root(),
        ))

        self.make_directories()
        theme.copy_static_files()
        self.copy_static_files()
        self.process()
        self.optimize()

    def build(self):
        print("Running chirun for directory {}".format(self.get_root_dir().resolve()))

        oembed.load_cache()

        self.load_config()

        self.load_themes()

        self.load_structure()

        for theme in self.themes:
            self.build_with_theme(theme)

        self.save_manifest()

        self.cleanup()

        oembed.save_cache()

def arg_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument('-o', '--output', dest='build_path', help='Set a directory to put build files in.\
            Defaults to a directory named \'build\' in the current directory.')
    parser.add_argument('-v', dest='verbose', action='store_true', help='Verbose output.')
    parser.add_argument('-vv', dest='veryverbose', action='store_true', help='Very verbose output.')
    parser.add_argument('-d', dest='cleanup_all', action='store_true', help='Delete auxiliary files.')
    parser.add_argument('-a', dest='absolute', action='store_true', help='Output using absolute file paths,\
            relative to the configured root_url.')
    parser.add_argument('--config', dest='config_file', help='Path to a config file. Defaults to \'config.yml\'.')
    parser.add_argument('-l', dest='local-deprecated', action='store_true', help='Deprecated and has no effect.\
            This option will be removed in a future version.')
    parser.add_argument('-z', dest='lazy-deprecated', action='store_true', help='Deprecated and has no effect.\
            This option will be removed in a future version.')
    parser.add_argument('dir', help='Path to a chirun compatible source directory.\
            Defaults to the current directory.', default='.', nargs='?')
    parser.add_argument('-f', dest='single_file', help='The path to a single file to build')
    parser.add_argument('--no-pdf',dest='build_pdf', action='store_false', help='Don\'t build PDF files')
    parser.set_defaults(build_pdf=None)
    return parser