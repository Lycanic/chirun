import logging
import os
import re
from makeCourse import slugify, yaml_header
from . import plastex

logger = logging.getLogger(__name__)

class Item(object):
	template_file = ''
	type = None

	def __init__(self, course, data, parent=None):
		self.course = course
		self.parent = parent
		self.data = data
		self.title = self.data.get('title',self.title)
		self.slug = slugify(self.title)
		self.source = self.data.get('source','')
		self.is_hidden = self.data.get('hidden',False)
		self.content = [load_item(course, obj, self) for obj in self.data.get('content',[])]

	def __str__(self):
		return '{} {}'.format(self.type, self.title)

	def yaml(self, active=False):
		item_yaml = {
			'title': self.title,
			'author': self.course.config['author'],
			'code': self.course.config['code'],
			'year': self.course.config['year'],
			'slug': self.slug,
			'theme': self.course.theme.yaml,
			'alt_themes': self.course.theme.alt_themes_yaml,
		}
		if active:
			item_yaml['active'] = 1
		return item_yaml


	def markdown(self,**kwargs):
		raise NotImplementedError("Item does not implement the markdown method")

	@property
	def out_path(self):
		if self.parent:
			return [self.parent.slug,self.slug]
		else:
			return [self.slug]

	@property
	def out_file(self):
		return os.path.join(*self.out_path)

	@property
	def url(self):
		return '/'.join(self.out_path)

	@property
	def url_clean(self):
		return '-'.join(self.out_path)

	@property	
	def in_file(self):
		base = os.path.basename(self.source)
		file,_ = os.path.splitext(self.source)
		return base

	@property	
	def base_file(self):
		basefile,_ = os.path.splitext(self.in_file)
		return basefile

	def get_content(self,force_local=False,out_format='html'):
		_, ext = os.path.splitext(self.source)

		if ext == '.md':
			mdContents = open(os.path.join(self.course.root_dir,self.source), 'r',encoding='utf-8').read()
			if mdContents[:3] == '---':
				logger.info('    Note: Markdown file {} contains a YAML header. It will be merged in...'.format(self.source))
				mdContents = re.sub(r'^---.*?---\n','',mdContents,re.S)
			mdContents = self.course.burnInExtras(mdContents,force_local,out_format)
			return mdContents
		elif ext == '.tex':
			return self.course.load_latex_content(self)
		else:
			raise Exception("Error: Unrecognised source type for {}: {}.".format(ch.title,ch.source))

class Part(Item):
	type = 'part'
	title = 'Untitled part'
	template_file = 'part.html'

	@property
	def out_path(self):
		return [self.slug]

	def yaml(self,active=False):
		item_yaml = super(Part, self).yaml(active)
		item_yaml.update({
			'part-slug': self.slug,
			'chapters': [item.yaml() for item in self.content if not item.is_hidden],
		})
		return item_yaml

	def markdown(self,**kwargs):
		return yaml_header(self.yaml())

class Url(Item):
	type = 'url'
	title = 'Untitled URL'
	template_file = 'part.html'

	def yaml(self,active=False):
		return {
			'title': self.title,
			'external_url': self.source,
		}

	def markdown(self,**kwargs):
		return None

class Chapter(Item):
	type = 'chapter'
	title = 'Untitled chapter'
	template_file = 'chapter.html'

	def yaml(self,active=False):
		item_yaml = super(Chapter, self).yaml(active)
		item_yaml.update({
			'build_pdf': self.course.config['build_pdf'],
			'file': '{}.html'.format(self.url),
			'pdf': '{}.pdf'.format(self.url),
			'sidebar': True,
		})
		return item_yaml

	def markdown(self,force_local=False,out_format='html'):
		header = self.yaml()

		if self.parent:
			header['part'] = self.parent.title
			header['part-slug'] = self.parent.slug
			header['chapters'] = [item.yaml(item==self) for item in self.parent.content if not item.is_hidden]
		else:
			header['chapters'] = [item.yaml(item==self) for item in self.course.structure if not item.type =='introduction' and not item.is_hidden]

		return yaml_header(header) + '\n\n' + self.get_content(force_local,out_format)

class Slides(Chapter):
	type = 'slides'
	title = 'Untitled Slides'
	template_file = 'slides.html'

	def yaml(self,active=False):
		item_yaml = super(Slides, self).yaml(active)
		item_yaml.update({
			'file': '{}.html'.format(self.url),
			'slides': '{}.slides.html'.format(self.url),
			'pdf': '{}.pdf'.format(self.url),
			'sidebar': True,
		})
		return item_yaml

class Recap(Chapter):
	type = 'recap'
	title = 'Untitled Recap'
	template_file = 'chapter.html'
	
	def yaml(self,active=False):
		item_yaml = super(Recap, self).yaml(active)
		item_yaml.update({
			'build_pdf': False,
			'file': '{}.html'.format(self.url),
			'sidebar': False,
		})
		return item_yaml

class Introduction(Item):
	type = 'introduction'
	template_file = 'index.html'
	title = 'index'
	out_path = ['index']

	def markdown(self,**kwargs):
		def link_yaml(s):
			if s.is_hidden:
				return
			return s.yaml()

		header = self.yaml()
		header['links'] = [link_yaml(s) for s in self.course.structure if not s.type =='introduction' and not s.is_hidden]
		
		struct = [s for s in self.course.structure if not s.type =='introduction' and not s.is_hidden]
		if len(struct) > 0 and struct[0].type == 'part':
			header['isPart'] = 1

		return yaml_header(header)+'\n\n'+self.get_content()

item_types = {
	'introduction': Introduction,
	'part': Part,
	'chapter': Chapter,
	'url': Url,
	'slides': Slides,
	'recap': Recap,
}

def load_item(course, data, parent=None):
	return item_types[data['type']](course, data, parent)
