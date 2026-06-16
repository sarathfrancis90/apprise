# BSD 2-Clause License
#
# Apprise - Push Notification Library.
# Copyright (c) 2026, Chris Caron <lead2gold@gmail.com>
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

from html.parser import HTMLParser
import re

from markdown import markdown

from .common import NotifyFormat
from .url import URLBase


def convert_between(from_format, to_format, content):
    """Converts between different suported formats. If no conversion exists, or
    the selected one fails, the original text will be returned.

    This function returns the content translated (if required)
    """

    converters = {
        (NotifyFormat.MARKDOWN, NotifyFormat.HTML): markdown_to_html,
        (NotifyFormat.TEXT, NotifyFormat.HTML): text_to_html,
        (NotifyFormat.HTML, NotifyFormat.TEXT): html_to_text,
        (NotifyFormat.HTML, NotifyFormat.MARKDOWN): html_to_markdown,
    }

    convert = converters.get((from_format, to_format))
    return convert(content) if convert else content


def markdown_to_html(content):
    """Converts specified content from markdown to HTML."""
    return markdown(
        content,
        extensions=["markdown.extensions.nl2br", "markdown.extensions.tables"],
    )


def text_to_html(content):
    """Converts specified content from plain text to HTML."""

    # First eliminate any carriage returns
    return URLBase.escape_html(content, convert_new_lines=True)


def html_to_text(content):
    """Converts a content from HTML to plain text."""

    parser = HTMLConverter()
    parser.feed(content)
    parser.close()
    return parser.converted


def html_to_markdown(content):
    """Converts a content from HTML to Markdown."""

    parser = HTMLMarkdownConverter()
    parser.feed(content)
    parser.close()
    return parser.converted


class HTMLConverter(HTMLParser):
    """An HTML to plain text converter tuned for email messages."""

    # The following tags must start on a new line
    BLOCK_TAGS = (
        "p",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "div",
        "td",
        "th",
        "code",
        "pre",
        "label",
        "li",
    )

    # the folowing tags ignore any internal text
    IGNORE_TAGS = (
        "form",
        "input",
        "textarea",
        "select",
        "ul",
        "ol",
        "style",
        "link",
        "meta",
        "title",
        "html",
        "head",
        "script",
    )

    # Condense Whitespace
    WS_TRIM = re.compile(r"[\s]+", re.DOTALL | re.MULTILINE)

    # Sentinel value for block tag boundaries, which may be consolidated into a
    # single line break.
    BLOCK_END = {}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Shoudl we store the text content or not?
        self._do_store = True

        # Initialize internal result list
        self._result = []

        # Initialize public result field (not populated until close() is
        # called)
        self.converted = ""

    def close(self):
        string = "".join(self._finalize(self._result))
        self.converted = string.strip()

    def _finalize(self, result):
        """Combines and strips consecutive strings, then converts consecutive
        block ends into singleton newlines.

        [ {be} " Hello " {be} {be} " World!" ] -> "\nHello\nWorld!"
        """

        # None means the last visited item was a block end.
        accum = None

        for item in result:
            if item == self.BLOCK_END:
                # Multiple consecutive block ends; do nothing.
                if accum is None:
                    continue

                # First block end; yield the current string, plus a newline.
                yield accum.strip() + "\n"
                accum = None

            # Multiple consecutive strings; combine them.
            elif accum is not None:
                accum += item

            # First consecutive string; store it.
            else:
                accum = item

        # Yield the last string if we have not already done so.
        if accum is not None:
            yield accum.strip()

    def handle_data(self, data, *args, **kwargs):
        """Store our data if it is not on the ignore list."""

        # initialize our previous flag
        if self._do_store:
            # Tidy our whitespace
            content = self.WS_TRIM.sub(" ", data)
            self._result.append(content)

    def handle_starttag(self, tag, attrs):
        """Process our starting HTML Tag."""
        # Toggle initial states
        self._do_store = tag not in self.IGNORE_TAGS

        if tag in self.BLOCK_TAGS:
            self._result.append(self.BLOCK_END)

        if tag == "li":
            self._result.append("- ")

        elif tag == "br":
            self._result.append("\n")

        elif tag == "hr":
            if self._result and isinstance(self._result[-1], str):
                self._result[-1] = self._result[-1].rstrip(" ")

            self._result.append("\n---\n")

        elif tag == "blockquote":
            self._result.append(" >")

    def handle_endtag(self, tag):
        """Edge case handling of open/close tags."""
        self._do_store = True

        if tag in self.BLOCK_TAGS:
            self._result.append(self.BLOCK_END)


class HTMLMarkdownConverter(HTMLConverter):
    """An HTML to Markdown converter tuned for notification messages."""

    # Override BLOCK_TAGS to exclude 'code' (handled inline with backticks)
    # and include 'samp' (treated as a fenced pre block like 'pre').
    BLOCK_TAGS = (
        "p",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "div",
        "td",
        "th",
        "pre",
        "samp",
        "label",
        "li",
    )

    # Escape content characters that carry special meaning in Markdown
    MARKDOWN_ESCAPE = re.compile(r"([`*#])", re.DOTALL | re.MULTILINE)

    # Matches the exact strings that <li> writes as bullet/number markers.
    # Used to detect when a BLOCK_END would separate a marker from its
    # first child element (e.g. <li><p>text</p></li>).
    # Pattern: optional leading spaces, then "- " or "N. "
    _LIST_MARKER_RE = re.compile(r"^\s*(?:\d+\.|-) $")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Context stack.  The sentinel root frame at index 0 is never
        # popped and represents top-level content outside every tag.
        # Each frame is a dict with these keys:
        #   tag         -- str|None  tag that opened this frame
        #   do_store    -- bool      store text nodes encountered here?
        #   preserve_cr -- bool      keep whitespace literally (pre/code)?
        #   list_type   -- str|None  'ul', 'ol', or None
        #   depth       -- int       list nesting depth (1 = outermost)
        #   counter     -- int|None  next item number for 'ol' lists
        #   href        -- str|None  href of an enclosing <a> tag; set
        #                            only on frames pushed by <a>
        self._stack = [
            {
                "tag": None,
                "do_store": True,
                "preserve_cr": False,
                "list_type": None,
                "depth": 0,
                "counter": None,
            }
        ]

    def _make_frame(self, tag, **overrides):
        """Return a new frame inheriting all fields from the current top."""

        # Copy every field from the parent frame as the default.
        # The root sentinel is never popped, so self._stack[-1] should
        # always succeed; the fallback guards against subclass misuse.
        parent = (
            self._stack[-1]
            if self._stack
            else {
                "tag": None,
                "do_store": True,
                "preserve_cr": False,
                "list_type": None,
                "depth": 0,
                "counter": None,
            }
        )
        frame = {
            "tag": tag,
            "do_store": parent["do_store"],
            "preserve_cr": parent["preserve_cr"],
            "list_type": parent["list_type"],
            "depth": parent["depth"],
            "counter": parent["counter"],
        }

        # Apply tag-specific overrides on top of the inherited defaults
        frame.update(overrides)
        return frame

    def _pop_to(self, tag):
        """Pop frames until the one opened by *tag* is removed.

        Scans from the top of the stack toward the root sentinel; if a
        matching frame is found it and all frames above it are removed.
        If no frame matches (unmatched close tag in malformed HTML) the
        call is silently a no-op -- the root sentinel is never popped.
        """
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i]["tag"] == tag:
                # Remove the matched frame and everything above it
                del self._stack[i:]
                return

    def _finalize(self, result):
        """Like the parent but uses rstrip() to preserve leading indent
        on list markers that come from items without a closing </li>."""

        # None means the last item was a block boundary
        accum = None

        for item in result:
            if item == self.BLOCK_END:
                # Multiple consecutive boundaries -- absorb silently
                if accum is None:
                    continue

                # Emit the current line, stripping only trailing space
                yield accum.rstrip() + "\n"
                accum = None

            # Combine consecutive string fragments
            elif accum is not None:
                accum += item

            # Start a new string accumulation
            else:
                accum = item

        # Emit any remaining content without a trailing newline.
        # rstrip() (not strip()) preserves leading indent from list
        # markers whose </li> was omitted.
        if accum is not None:
            yield accum.rstrip()

    def handle_data(self, data, *args, **kwargs):
        """Store data, escaping Markdown special characters."""

        # Read current context from the stack top
        ctx = self._stack[-1]

        # Discard text when the current context suppresses content
        if not ctx["do_store"]:
            return

        # Preserve whitespace literally inside code/pre blocks;
        # collapse runs to a single space everywhere else
        content = data if ctx["preserve_cr"] else self.WS_TRIM.sub(" ", data)

        # Drop whitespace-only nodes that sit right after a block
        # boundary or right after a list marker -- both are HTML
        # indentation artifacts that must not appear as leading spaces
        if (
            not ctx["preserve_cr"]
            and not content.strip()
            and (
                not self._result
                or self._result[-1] == self.BLOCK_END
                or (
                    isinstance(self._result[-1], str)
                    and self._LIST_MARKER_RE.match(self._result[-1])
                )
            )
        ):
            return

        # Escape special Markdown characters outside code/pre blocks --
        # backtick and fence delimiters already make content literal
        if not ctx["preserve_cr"]:
            content = self.MARKDOWN_ESCAPE.sub(r"\\\1", content)

        self._result.append(content)

    def handle_starttag(self, tag, attrs):
        """Process a starting HTML tag."""

        # Capture the context before any push so list markers read
        # the parent's depth and counter
        ctx = self._stack[-1]

        # List containers: suppress direct text, track list kind

        if tag in ("ul", "ol"):
            self._stack.append(
                self._make_frame(
                    tag,
                    do_store=False,
                    list_type=tag,
                    depth=ctx["depth"] + 1,
                    counter=(1 if tag == "ol" else None),
                )
            )
            return

        # List items: re-enable text storage and emit a marker

        if tag == "li":
            # Indent scales with nesting depth (depth 1 = no indent)
            indent = "  " * (ctx["depth"] - 1)
            if ctx["list_type"] == "ol" and ctx["counter"] is not None:
                marker = "{}{}. ".format(indent, ctx["counter"])
            else:
                marker = "{}- ".format(indent)

            # Push a frame that re-enables text storage for this item
            self._stack.append(self._make_frame(tag, do_store=True))

            # Block boundary before the marker so it starts on its own line
            self._result.append(self.BLOCK_END)
            self._result.append(marker)
            return

        # Literal-whitespace blocks: stop collapsing whitespace

        if tag in ("code", "pre", "samp"):
            self._stack.append(self._make_frame(tag, preserve_cr=True))

        # <body> re-enables storage after a suppressing <html> frame

        elif tag == "body":
            self._stack.append(self._make_frame(tag, do_store=True))

        # All other IGNORE_TAGS: suppress enclosed text

        elif tag in self.IGNORE_TAGS:
            self._stack.append(self._make_frame(tag, do_store=False))

        # Block boundary before block-level content.
        # Exception: when a block element is the first child of a <li>,
        # the marker ("- " or "N. ") is already in _result[-1] and a
        # BLOCK_END would put them on separate lines.  Suppress it so
        # the marker and the first block child share the same line.

        if tag in self.BLOCK_TAGS:
            if (
                self._result
                and isinstance(self._result[-1], str)
                and self._LIST_MARKER_RE.match(self._result[-1])
            ):
                pass  # suppress; marker and content stay on one line

            else:
                self._result.append(self.BLOCK_END)

        # Tag-specific Markdown output

        if tag == "br":
            self._result.append("\n")

        elif tag == "hr":
            # Strip trailing space from the previous token so the rule
            # renders flush against the surrounding content
            if self._result and isinstance(self._result[-1], str):
                self._result[-1] = self._result[-1].rstrip(" ")

            self._result.append("\n---\n")

        elif tag == "blockquote":
            self._result.append("> ")

        elif tag == "h1":
            self._result.append("# ")

        elif tag == "h2":
            self._result.append("## ")

        elif tag == "h3":
            self._result.append("### ")

        elif tag == "h4":
            self._result.append("#### ")

        elif tag == "h5":
            self._result.append("##### ")

        elif tag == "h6":
            self._result.append("###### ")

        elif tag in ("strong", "b"):
            self._result.append("**")

        elif tag in ("em", "i"):
            self._result.append("*")

        elif tag == "code":
            # Inline code -- backtick pair with no surrounding block boundary
            self._result.append("`")

        elif tag in ("pre", "samp"):
            # Opening fence; BLOCK_END above puts it on its own line;
            # a second BLOCK_END ensures content starts on a new line
            self._result.append("```")
            self._result.append(self.BLOCK_END)

        elif tag == "a":
            # Push a frame that carries the href so ALL content between
            # <a> and </a> -- including nested bold/italic -- is wrapped
            # in Markdown link syntax by handle_endtag("a")
            href = next(
                (v for k, v in attrs if k == "href"),
                None,
            )
            if href is not None:
                self._stack.append(self._make_frame(tag, href=href))
                self._result.append("[")

    def handle_endtag(self, tag):
        """Edge case handling of close tags."""

        # Links: retrieve the href from the <a> frame, pop it, then
        # close the Markdown link -- all content written between <a>
        # and </a> (bold, italic, raw text) is now inside the brackets
        if tag == "a":
            # Find the href stored in the nearest <a> frame
            href = None
            for frame in reversed(self._stack):
                if frame["tag"] == "a":
                    href = frame.get("href")
                    break

            self._pop_to(tag)

            # Only emit the closing if there was an href; a bare <a>
            # without href (anchor target) is treated as a no-op
            if href is not None:
                self._result.append("](" + href + ")")

            return

        # List containers: pop the frame and return

        if tag in ("ul", "ol"):
            self._pop_to(tag)
            return

        # List items: emit boundary, pop, then advance ol counter

        if tag == "li":
            # Block boundary closes the item content
            self._result.append(self.BLOCK_END)

            # Pop the li frame; parent ul/ol frame is now on top
            self._pop_to(tag)

            # Advance the ordered-list counter in the parent frame
            ctx = self._stack[-1]
            if ctx["list_type"] == "ol":
                ctx["counter"] += 1

            return

        # Emit closing markers before popping the frame

        # Block boundary after block-level content
        if tag in self.BLOCK_TAGS:
            self._result.append(self.BLOCK_END)

        if tag in ("strong", "b"):
            self._result.append("**")

        elif tag in ("em", "i"):
            self._result.append("*")

        elif tag == "code":
            # Close the inline backtick pair
            self._result.append("`")

        elif tag in ("pre", "samp"):
            # BLOCK_END from BLOCK_TAGS above ends the content line;
            # the closing fence and a second BLOCK_END close the block
            self._result.append("```")
            self._result.append(self.BLOCK_END)

        # Pop frames for all tags that pushed them

        if tag in ("code", "pre", "samp", "body") or tag in self.IGNORE_TAGS:
            self._pop_to(tag)
