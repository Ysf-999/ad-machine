"""Private font-resolution environment for libass wrappers; no tool edits."""
import pathlib
from xml.sax.saxutils import escape

def configuration(fonts,directory):
 original=pathlib.Path(fonts)
 if original.is_symlink():raise ValueError('Symlink font directory refused')
 fonts=original.resolve();directory=pathlib.Path(directory).absolute()
 if not fonts.is_dir() or fonts.is_symlink():raise ValueError('Declared font directory required')
 directory.mkdir(parents=True,exist_ok=True);cache=directory/'cache';cache.mkdir(exist_ok=True)
 config=directory/'fonts.conf';config.write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig><dir>'+escape(str(fonts))+'</dir><cachedir>'+escape(str(cache))+'</cachedir><config><rescan><int>0</int></rescan></config></fontconfig>')
 return {'FONTCONFIG_FILE':str(config),'FONTCONFIG_PATH':str(directory),'XDG_CACHE_HOME':str(cache),'ADMACHINE_FONTS_DIR':str(fonts)}
def ass_filter(ass,fonts):
 for value in [ass,fonts]:
  if not pathlib.Path(value).is_absolute() or any(c in str(value) for c in ":,'[];\\\n\r\x00"):raise ValueError('Unambiguous absolute filter paths required')
 return 'ass='+str(ass)+':fontsdir='+str(fonts)
