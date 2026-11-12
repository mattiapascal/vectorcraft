// Personal FreeHand bridge. Uses the public libfreehand/librevenge interfaces.
#include <libfreehand/libfreehand.h>
#include <librevenge-stream/librevenge-stream.h>
#include <librevenge-generators/librevenge-generators.h>
#include <iostream>
#include <cstdio>
#include <cstring>
#include "text_capture.h"
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

int main(int argc, char **argv) {
  if (argc == 2 && !std::strcmp(argv[1], "--version")) {
    std::cout << "FreeHand Bridge protocol FHI1; libfreehand 0.1.3\n";
    return 0;
  }
  if (argc != 2) {
    std::cerr << "Usage: fh_extract INPUT\n";
    return 2;
  }
  try {
    librevenge::RVNGFileStream input(argv[1]);
    if (!libfreehand::FreeHandDocument::isSupported(&input)) {
      std::cerr << "Formato FreeHand non supportato o file danneggiato.\n";
      return 3;
    }
    input.seek(0, librevenge::RVNG_SEEK_SET);
    librevenge::RVNGStringVector pages;
    FHITextCapture generator(pages);
    if (!libfreehand::FreeHandDocument::parse(&input, &generator) || pages.empty()) {
      std::cerr << "Impossibile interpretare il documento FreeHand.\n";
      return 4;
    }
    for (unsigned i = 0; i < pages.size(); ++i) {
      if (pages[i].empty()) {
        std::cerr << "Pagina SVG vuota: " << i + 1 << '\n';
        return 5;
      }
    }
#ifdef _WIN32
    _setmode(_fileno(stdout), _O_BINARY);
#endif
    std::cout << "FHI1\n" << pages.size() << '\n';
    for (unsigned i = 0; i < pages.size(); ++i) {
      const char *svg = pages[i].cstr();
      const auto length = std::strlen(svg);
      std::cout << length << '\n';
      std::cout.write(svg, length);
    }
    return std::cout.good() ? 0 : 6;
  } catch (...) {
    std::cerr << "Errore del parser FreeHand.\n";
    return 7;
  }
}
