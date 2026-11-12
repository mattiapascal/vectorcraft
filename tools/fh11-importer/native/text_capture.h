// Retain text structure which the SVG drawing generator otherwise flattens.
#pragma once
#include <librevenge/librevenge.h>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

inline std::string fhiJsonString(const std::string &value) {
  std::ostringstream out;
  out << '"';
  for (unsigned char c : value) {
    if (c == '"' || c == '\\') out << '\\' << c;
    else if (c < 32) {
      const char *hex = "0123456789abcdef";
      out << "\\u00" << hex[c >> 4] << hex[c & 15];
    } else out << c;
  }
  out << '"';
  return out.str();
}

inline std::string fhiJsonProps(const librevenge::RVNGPropertyList &props) {
  std::ostringstream out;
  out << '{';
  bool first = true;
  librevenge::RVNGPropertyList::Iter it(props);
  for (it.rewind(); it.next();) {
    if (it.child() || !it()) continue;
    if (!first) out << ',';
    first = false;
    out << fhiJsonString(it.key()) << ':' << fhiJsonString(it()->getStr().cstr());
  }
  out << '}';
  return out.str();
}

class FHITextCapture : public librevenge::RVNGSVGDrawingGenerator {
  struct Span { librevenge::RVNGPropertyList props; std::string text; };
  struct Paragraph { librevenge::RVNGPropertyList props; std::vector<Span> spans; };
  librevenge::RVNGPropertyList objectProps, spanProps;
  std::vector<Paragraph> paragraphs;
  unsigned index = 0;
  bool inText = false;
  void append(const char *text) {
    if (!inText) return;
    if (paragraphs.empty()) paragraphs.emplace_back();
    auto &spans = paragraphs.back().spans;
    Span span;
    span.props = spanProps;
    span.text = text;
    spans.push_back(span);
  }
public:
  explicit FHITextCapture(librevenge::RVNGStringVector &pages)
      : librevenge::RVNGSVGDrawingGenerator(pages, "") {}
  void startTextObject(const librevenge::RVNGPropertyList &props) override {
    ++index;
    objectProps = props;
    spanProps.clear();
    paragraphs.clear();
    inText = true;
    librevenge::RVNGSVGDrawingGenerator::startTextObject(props);
  }
  void openParagraph(const librevenge::RVNGPropertyList &props) override {
    if (inText) {
      paragraphs.emplace_back();
      paragraphs.back().props = props;
    }
    librevenge::RVNGSVGDrawingGenerator::openParagraph(props);
  }
  void openSpan(const librevenge::RVNGPropertyList &props) override {
    spanProps = props;
    librevenge::RVNGSVGDrawingGenerator::openSpan(props);
  }
  void insertText(const librevenge::RVNGString &value) override {
    append(value.cstr());
    librevenge::RVNGSVGDrawingGenerator::insertText(value);
  }
  void insertSpace() override {
    append(" ");
    librevenge::RVNGSVGDrawingGenerator::insertSpace();
  }
  void insertTab() override {
    append("\t");
    librevenge::RVNGSVGDrawingGenerator::insertTab();
  }
  void insertLineBreak() override {
    append("\n");
    librevenge::RVNGSVGDrawingGenerator::insertLineBreak();
  }
  void endTextObject() override {
    std::ostringstream out;
    out << "FHTEXT {\"index\":" << index << ",\"props\":" << fhiJsonProps(objectProps)
        << ",\"paragraphs\":[";
    for (size_t i = 0; i < paragraphs.size(); ++i) {
      if (i) out << ',';
      out << "{\"props\":" << fhiJsonProps(paragraphs[i].props) << ",\"spans\":[";
      const auto &spans = paragraphs[i].spans;
      for (size_t j = 0; j < spans.size(); ++j) {
        if (j) out << ',';
        out << "{\"props\":" << fhiJsonProps(spans[j].props) << ",\"text\":"
            << fhiJsonString(spans[j].text) << '}';
      }
      out << "]}";
    }
    out << "]}\n";
    std::cerr << out.str();
    inText = false;
    librevenge::RVNGSVGDrawingGenerator::endTextObject();
  }
};
