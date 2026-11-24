"""The CodeNOW logo of the sandbox hub: one title row and one favicon for every hub page.

Static trusted SVG (from the CodeNOW brand assets), inlined: the hub makes no external request and serves no file.
The wordmark uses currentColor, so it follows the page's text colour in the light and the dark style. Never
interpolate data into these constants; title_row escapes only the title that it gets.
"""
from __future__ import annotations

import base64
from html import escape

GRADIENT_ID = "cnlogo-g"

_HEX = (
    '<path fill-rule="evenodd" clip-rule="evenodd" d="M32.2264 7.18981L21.7916 1.03741C19.4487 -0.345803 16.5648 '
    '-0.345803 14.2219 1.03741L3.78719 7.18501C1.44431 8.56822 0 11.1185 0 13.8801V26.1849C0 28.9466 1.44431 '
    '31.4968 3.78719 32.8753L14.2219 39.0277C16.5648 40.4109 19.4487 40.4109 21.7916 39.0277L32.2264 32.8801C34.5693 '
    '31.4968 36.0136 28.9466 36.0136 26.1849V13.8849C36.0136 11.1233 34.5693 8.56822 32.2264 7.18981Z" '
    'fill="url(#{gid})"/>'
    '<path fill-rule="evenodd" clip-rule="evenodd" d="M19.2078 33.4807L29.0349 27.8067L28.3584 27.4162C25.8066 '
    '25.9428 22.5439 25.13 19.2078 24.9778V33.4807Z" fill="white"/>'
    '<rect width="2.3897" height="11.9471" transform="matrix(1.6124e-05 -1 0.866034 0.499986 6.45984 27.4852)" '
    'fill="white"/>'
    '<rect width="2.39366" height="11.9475" transform="matrix(1.6124e-05 -1 0.866034 0.499986 6.45984 22.3834)" '
    'fill="white"/>'
    '<path d="M6.45984 17.2907L6.45988 14.8991L14.7349 19.6765C15.8788 20.3369 16.8061 21.943 16.8061 23.2639L6.45984 '
    '17.2907Z" fill="white"/>'
    '<path d="M16.3208 7.22318C17.2487 6.70236 18.753 6.70236 19.6809 7.22318L29.4111 12.6849C23.116 16.2184 12.8976 '
    '16.2117 6.60253 12.6782L16.3208 7.22318Z" fill="white"/>'
    '<defs><radialGradient id="{gid}" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" '
    'gradientTransform="translate(11.644 55.1153) rotate(-62.7517) scale(46.3893 22.5723)">'
    # the hexagon's own dark end, not the wordmark colour: it stays dark in the dark style too
    '<stop stop-color="#003566"/><stop offset="1" stop-color="rgb(34,37,51)"/></radialGradient></defs>'
)

_WORDMARK = "".join(f'<path d="{d}" fill="currentColor"/>' for d in (
    "M49.2056 6.28333C53.3636 6.28333 55.5097 7.89175 55.778 10.8405H53.0954C52.693 9.23211 51.4858 8.56193 49.2056 "
    "8.56193C46.5229 8.56193 45.3158 9.50019 45.3158 11.6448C45.3158 13.7893 46.5229 14.7276 49.2056 14.7276C51.4858 "
    "14.7276 52.693 14.0574 52.9612 12.3149H55.6438C55.3756 15.3978 53.2295 16.8722 49.0714 16.8722C44.511 16.8722 "
    "42.499 14.9957 42.499 11.5107C42.6332 8.29386 44.6451 6.28333 49.2056 6.28333Z",
    "M57.7905 12.583C57.7905 9.36618 60.2049 8.02582 63.8264 8.02582C67.4479 8.02582 69.8623 9.36618 69.8623 "
    "12.583C69.8623 15.7999 67.4479 17.1403 63.8264 17.1403C60.2049 17.1403 57.7905 15.7999 57.7905 12.583ZM67.448 "
    "12.583C67.448 10.7065 66.2408 10.1704 63.9605 10.1704C61.5462 10.1704 60.4731 10.7065 60.4731 12.583C60.4731 "
    "14.4595 61.6803 14.9957 63.9605 14.9957C66.2408 14.9957 67.448 14.3255 67.448 12.583Z",
    "M84.0789 4.94312V16.8723H81.5305V15.5319C80.5915 16.4702 78.982 17.0063 77.1041 17.0063C74.2874 17.0063 71.873 "
    "15.8 71.873 12.4491C71.873 9.09822 74.2874 7.8919 77.1041 7.8919C78.982 7.8919 80.5915 8.42805 81.5305 "
    "9.3663V4.94312H84.0789ZM81.5305 12.5832C81.5305 10.8407 80.3233 10.1705 78.0431 10.1705C75.7628 10.1705 74.5557 "
    "10.8407 74.5557 12.5832C74.5557 14.3256 75.7628 14.9958 78.0431 14.9958C80.3233 14.9958 81.5305 14.3256 81.5305 "
    "12.5832Z",
    "M95.8164 13.7894H98.3649C97.8284 16.068 95.5481 17.1403 92.329 17.1403C88.9757 17.1403 86.4272 15.7999 86.4272 "
    "12.583C86.4272 9.36618 88.9757 8.02582 92.4631 8.02582C95.8164 8.02582 98.499 9.0981 98.499 13.1192H88.9757C89.244 "
    "14.4595 90.5853 14.9957 92.329 14.9957C94.0727 14.9957 95.1458 14.7276 95.8164 13.7894ZM89.1099 "
    "11.5107H95.8164C95.414 10.3044 94.0727 9.90232 92.4631 9.90232C90.7194 9.90232 89.5123 10.3044 89.1099 11.5107Z",
    "M58.1063 19.5099V30.7654H54.2177L46.5747 22.3238V30.7654H43.6248V19.5099H47.5133L55.1563 27.9515V19.5099H58.1063Z",
    "M59.9722 25.1372C59.9722 21.3854 62.1176 19.3755 67.0788 19.3755C72.0401 19.3755 74.1855 21.3854 74.1855 "
    "25.1372C74.1855 28.889 72.0401 30.8989 67.0788 30.8989C61.9835 30.8989 59.9722 28.7551 59.9722 25.1372ZM71.2356 "
    "25.1372C71.2356 22.8594 70.0288 21.7874 67.0788 21.7874C64.1289 21.7874 62.9221 22.8594 62.9221 25.1372C62.9221 "
    "27.4151 64.1289 28.4871 67.0788 28.4871C70.0288 28.4871 71.2356 27.4151 71.2356 25.1372Z",
    "M97.7848 19.5096L93.3599 30.765H89.3373L85.9851 22.1895L82.6329 30.6311H78.6102L74.1853 19.5096H77.2693L80.6215 "
    "28.3532L84.1078 19.5096H87.7282L91.2145 28.3532L94.5667 19.5096H97.7848Z",
))

LOGO_SVG = ('<svg class="cnlogo" viewBox="0 0 99 41" fill="none" role="img" aria-label="CodeNOW">'
            + _HEX.replace("{gid}", GRADIENT_ID) + _WORDMARK + "</svg>")

# The mark alone (the hexagon) as the tab icon; base64, so its markup never shows in the page's own HTML.
_MARK = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 37 41" fill="none">'
         + _HEX.replace("{gid}", "g") + "</svg>")
FAVICON_LINK = ('<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,'
                + base64.b64encode(_MARK.encode("ascii")).decode("ascii") + '">')

LOGO_STYLE = """
.titlerow{display:flex;align-items:center;gap:12px;margin:0 0 4px}.titlerow h1{margin:0;min-width:0;overflow-wrap:anywhere}
.titlerow a.home{display:inline-flex;color:var(--text);flex:none}.cnlogo{display:block;height:28px;width:auto}
"""


def title_row(title: str) -> str:
    """The logo (a link to the hub index) and the page's h1; the title is escaped here."""
    return (f'<div class="titlerow"><a class="home" href="/" title="All sandboxes">{LOGO_SVG}</a>'
            f"<h1>{escape(title, quote=True)}</h1></div>")
