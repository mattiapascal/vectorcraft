"""Recover FreeHand metadata and correct explicit appearance-list inheritance.

Modified upstream source files retain their MPL-2.0 notices in build/parser-pages.
This script is the reproducible record of our modifications.
"""
from pathlib import Path
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.runtime/python'))


def prepare_icu():
    sdk = ROOT / '.runtime/ucrt64'
    if (sdk / 'include/unicode/utf8.h').exists():
        return
    import zstandard
    entries = list((ROOT / '.runtime/packages/database').glob('mingw-w64-ucrt-x86_64-icu-*/desc'))
    if len(entries) != 1:
        raise RuntimeError('Refresh the MSYS2 package database first.')
    fields = {}
    for block in entries[0].read_text(encoding='utf-8').strip().split('\n\n'):
        lines = block.splitlines()
        fields[lines[0].strip('%')] = lines[1:]
    name, digest = fields['FILENAME'][0], fields['SHA256SUM'][0]
    target = ROOT / '.runtime/packages' / name
    if not target.exists():
        print('Download ICU headers:', name, flush=True)
        with urllib.request.urlopen('https://repo.msys2.org/mingw/ucrt64/' + name, timeout=120) as r:
            target.write_bytes(r.read())
    if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        raise RuntimeError('ICU checksum mismatch')
    with target.open('rb') as source, zstandard.ZstdDecompressor().stream_reader(source) as reader:
        with tarfile.open(fileobj=reader, mode='r|') as archive:
            for member in archive:
                if member.name.startswith(('ucrt64/include/unicode/', 'ucrt64/share/licenses/icu/')):
                    archive.extract(member, ROOT / '.runtime', filter='data')


def prepare_sources():
    """Apply the same parser corrections for both native build platforms."""
    archive = ROOT / '.runtime/source/libfreehand-0.1.3.tar.xz'
    archive.parent.mkdir(parents=True, exist_ok=True)
    expected = 'a431d78767e5aa27ade7c6d1b7a11a9f1848cb4b9260bf0a6a44689553ecccfe'
    if not archive.exists():
        with urllib.request.urlopen('https://dev-www.libreoffice.org/src/libfreehand/libfreehand-0.1.3.tar.xz', timeout=120) as r:
            archive.write_bytes(r.read())
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise RuntimeError('libfreehand source checksum mismatch')
    with tarfile.open(archive) as tar:
        tar.extractall(archive.parent, filter='data')
    source = ROOT / '.runtime/source/libfreehand-0.1.3'
    target = ROOT / 'build/parser-pages'
    shutil.copytree(source, target, dirs_exist_ok=True)
    lib = target / 'src/lib'
    utils = lib / 'libfreehand_utils.h'
    utils.write_text(utils.read_text().replace('#include <boost/cstdint.hpp>', '#include <cstdint>'))
    parser = lib / 'FHParser.cpp'
    text = parser.read_text()
    text = text.replace('#include <algorithm>', '#include <algorithm>\n#include <iostream>\n#include <iomanip>')
    start = text.index('void libfreehand::FHParser::readVMpObj(')
    end = text.index('void libfreehand::FHParser::readXform(', start)
    part = text[start:end]
    part = part.replace('  double minX = 0.0;', '''  unsigned pageFlags = 0;
  double pageWidth = 0, pageHeight = 0;
  double pageX = 0, pageY = 0;
  bool hasPageX = false, hasPageY = false;
  double minX = 0.0;''')
    # MX can store both the page position and a secondary position. Keep
    # libfreehand's artwork origin and use the primary coordinates for the box.
    for axis, flag in [('X', 1), ('Y', 2)]:
        field = f'      min{axis} = _readCoordinate(input) / 72.0;'
        if part.count(field) != 1:
            raise RuntimeError('Unexpected upstream page position reader')
        part = part.replace(field, f'''      pageFlags |= {flag};
{field}
      if (rec == FH_PAGE_START_{axis} || !hasPage{axis})
        page{axis} = min{axis};
      hasPage{axis} = hasPage{axis} || rec == FH_PAGE_START_{axis};''')
    part = part.replace('      maxX = minX + _readCoordinate(input) / 72.0;', '      pageFlags |= 4;\n      pageWidth = _readCoordinate(input) / 72.0;\n      maxX = minX + pageWidth;')
    part = part.replace('      maxY = minY + _readCoordinate(input) / 72.0;', '      pageFlags |= 8;\n      pageHeight = _readCoordinate(input) / 72.0;\n      maxY = minY + pageHeight;')
    part = part.replace('''      if (key == 2)
        _readRecordId(input);
      else''', '''      if (key == 2) {
        unsigned reference = _readRecordId(input);
        if (rec == 0x1369) std::cerr << "FHLINEREF " << m_currentRecord + 1 << " " << reference << "\\n";
      }
      else''')
    marker = '  if (collector)\n  {\n    if (charProps)'
    if marker not in part:
        raise RuntimeError('Unexpected upstream page reader')
    part = part.replace(marker, '''  if (pageFlags == 15 && pageWidth > 0 && pageHeight > 0)
    std::cerr << std::setprecision(17) << "FHPAGE " << m_currentRecord + 1 << " "
              << pageX << " " << pageY << " " << pageWidth << " " << pageHeight << "\\n";
''' + marker)
    text = text[:start] + part + text[end:]
    old = '''    input->seek(48, librevenge::RVNG_SEEK_CUR);
    _readRecordId(input);'''
    new = '''    unsigned long count = 0;
    const unsigned char *row = input->read(48, count);
    if (count != 48) throw EndOfStreamException();
    const char *digits = "0123456789abcdef";
    std::cerr << "FHLINEROW " << m_currentRecord + 1 << " " << i << " ";
    for (unsigned j = 0; j < 48; ++j) std::cerr << digits[row[j] >> 4] << digits[row[j] & 15];
    std::cerr << " " << _readRecordId(input) << "\\n";'''
    if text.count(old) != 1:
        raise RuntimeError('Unexpected upstream line table reader')
    text = text.replace(old, new)
    begin = text.index('void libfreehand::FHParser::readTextObject(')
    finish = text.index('void libfreehand::FHParser::readTileFill(', begin)
    text_part = text[begin:finish]
    marker = '    default:\n      if ((key >> 16) == 2)'
    if text_part.count(marker) != 1:
        raise RuntimeError('Unexpected upstream text frame reader')
    text_part = text_part.replace(marker, '''    case FH_LINETABLE_ID: {
      unsigned reference = _readRecordId(input);
      std::cerr << "FHLINEREF " << textObject.m_vmpObjId << " " << reference << "\\n";
      break;
    }
''' + marker)
    text = text[:begin] + text_part + text[finish:]
    parser.write_text(text)
    collector = lib / 'FHCollector.cpp'
    text = collector.read_text().replace('#include <algorithm>', '#include <algorithm>\n#include <iostream>\n#include <iomanip>')
    marker = '  painter->startDocument(librevenge::RVNGPropertyList());'
    if text.count(marker) != 1:
        raise RuntimeError('Unexpected upstream document output')
    text = text.replace(marker, '''  std::cerr << std::setprecision(17) << "FHORIGIN " << m_pageInfo.m_minX << " " << m_pageInfo.m_maxY << "\\n";
''' + marker)
    text = text.replace('      painter->startTextObject(textObjectProps);',
                        '''      textObjectProps.insert("fhi:vmp", int(textObject->m_vmpObjId));
      textObjectProps.insert("fhi:raw-left", textObject->m_startX);
      textObjectProps.insert("fhi:raw-y", textObject->m_startY);
      textObjectProps.insert("fhi:raw-width", textObject->m_width);
      textObjectProps.insert("fhi:raw-height", textObject->m_height);
      painter->startTextObject(textObjectProps);''')
    old = 'propList.insert("fo:letter-spacing", it->second*charProps.m_fontSize, librevenge::RVNG_POINT);'
    if text.count(old) != 1:
        raise RuntimeError('Unexpected upstream tracking conversion')
    text = text.replace(old, '''propList.insert("fhi:raw-tracking", it->second, librevenge::RVNG_PERCENT);
      propList.insert("fhi:tracking-font-size", charProps.m_fontSize, librevenge::RVNG_POINT);
      propList.insert("fo:letter-spacing", it->second *
          (propList["fo:font-size"] ? propList["fo:font-size"]->getDouble() : charProps.m_fontSize),
          librevenge::RVNG_POINT);''')
    # MX GraphicStyle attribute lists replace the parent's paint list. A child
    # with its own fill-only (or empty) list must not acquire the parent's stroke.
    # A missing list still inherits. PropList-based older formats are unchanged.
    for method, following in [('_appendFillProperties', '_appendStrokeProperties'),
                              ('_appendStrokeProperties', '_appendBasicFill')]:
        start = text.index('void libfreehand::FHCollector::' + method + '(')
        end = text.index('void libfreehand::FHCollector::' + following + '(', start)
        part = text[start:end]
        old = 'if (graphicStyle->m_parentId)'
        if part.count(old) != 1:
            raise RuntimeError('Unexpected upstream appearance inheritance')
        part = part.replace(old, 'if (graphicStyle->m_parentId && !graphicStyle->m_attrId)')
        text = text[:start] + part + text[end:]
    collector.write_text(text)
    return target


def main():
    prepare_icu()
    target = prepare_sources()
    lib = target / 'src/lib'
    sdk = ROOT / '.runtime/ucrt64'
    env = os.environ.copy()
    env['PATH'] = str(sdk / 'bin') + os.pathsep + env.get('PATH', '')
    includes = [sdk / 'include/librevenge-0.0', sdk / 'include', target / 'inc', lib]
    args = [str(sdk / 'bin/g++.exe'), '-std=c++17', '-O2', '-Wno-deprecated-declarations']
    args += ['-I' + str(p) for p in includes]
    args += [str(ROOT / 'native/fh_extract.cpp')] + [str(p) for p in lib.glob('*.cpp')]
    args += ['-L' + str(sdk / 'lib'), '-lrevenge-generators-0.0', '-lrevenge-stream-0.0', '-lrevenge-0.0', '-llcms2', '-lz', '-o', str(ROOT / 'build/fh_extract_pages.exe')]
    subprocess.run(args, env=env, check=True)
    print('Ready: build/fh_extract_pages.exe')
    if '--test' in sys.argv:
        test_args = args[:]
        test_args[test_args.index(str(ROOT / 'native/fh_extract.cpp'))] = str(ROOT / 'tests/style_resolution.cpp')
        test_exe = ROOT / 'build/test_style_resolution.exe'
        test_args[-1] = str(test_exe)
        subprocess.run(test_args, env=env, check=True)
        subprocess.run([str(test_exe)], env=env, check=True)
        print('Style tests passed: explicit stroke, absent stroke, empty list, inheritance, fill, width.')


if __name__ == '__main__':
    main()
