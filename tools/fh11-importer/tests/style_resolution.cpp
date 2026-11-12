// Regression checks for the patched MX appearance-list resolver.
#include <cassert>
#include <deque>
#include <map>
#include <stack>
#include <librevenge/librevenge.h>
#include "FHTransform.h"
#include "FHTypes.h"
#include "FHPath.h"
// Exercise the resolver directly without extending the production API.
#define private public
#include "FHCollector.h"
#undef private

int main() {
  using namespace libfreehand;
  FHCollector c;
  FHBasicLine line; line.m_width = 2.5 / 72.0;
  c.collectBasicLine(1, line);
  FHBasicFill fill; c.collectBasicFill(2, fill);
  FHAttributeHolder stroke; stroke.m_attrId = 1;
  c.collectAttributeHolder(3, stroke);
  FHAttributeHolder paint; paint.m_attrId = 2;
  c.collectAttributeHolder(4, paint);
  FHList strokeOnly; strokeOnly.m_elements = {3}; c.collectList(5, strokeOnly);
  FHList fillOnly; fillOnly.m_elements = {4}; c.collectList(6, fillOnly);
  FHList both; both.m_elements = {3, 4}; c.collectList(7, both);
  FHList empty; c.collectList(8, empty);
  FHGraphicStyle parent; parent.m_attrId = 7; c.collectGraphicStyle(9, parent);
  for (unsigned list : {0u, 5u, 6u, 7u, 8u}) {
    FHGraphicStyle child; child.m_parentId = 9; child.m_attrId = list;
    c.collectGraphicStyle(10, child);
    librevenge::RVNGPropertyList props;
    c._appendStrokeProperties(props, 10);
    c._appendFillProperties(props, 10);
    bool hasStroke = list == 0 || list == 5 || list == 7;
    bool hasFill = list == 0 || list == 6 || list == 7;
    assert((props["draw:stroke"]->getStr() != "none") == hasStroke);
    assert((props["draw:fill"]->getStr() != "none") == hasFill);
    if (hasStroke) assert(props["svg:stroke-width"]->getDouble() == 2.5 / 72.0);
  }
  return 0;
}
