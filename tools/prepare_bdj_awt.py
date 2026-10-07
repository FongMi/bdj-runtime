"""Keep upstream AWT JNI initialization without importing the desktop X11 backend."""

import pathlib
import re
import sys


def extract_function(source, symbol):
    pattern = r"JNIEXPORT\s+void\s+JNICALL\s+" + re.escape(symbol) + r"\s*\([^{}]*\)\s*\{"
    matches = list(re.finditer(pattern, source))
    if len(matches) != 1:
        raise ValueError("Expected one upstream initializer: " + symbol)
    match = matches[0]
    depth = 1
    end = match.end()
    while depth and end < len(source):
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    if depth:
        raise ValueError("Unbalanced upstream initializer: " + symbol)
    return source[match.start():end]


def prepare_build_rules(text):
    original = "    LIBAWT_XAWT_FILES := list.c\n"
    dependency = (
        "ifneq (, $(findstring $(OPENJDK_TARGET_OS), solaris aix))\n"
        "  $(BUILD_LIBFONTMANAGER): $(BUILD_LIBAWT_HEADLESS)\n"
        "endif\n"
    )
    if text.count(original) != 1:
        raise ValueError("Android port AWT source list changed")
    if text.count(dependency) != 1:
        raise ValueError("Android port AWT dependency block changed")
    return text.replace(original, "    LIBAWT_XAWT_FILES := AwtInitIDs.c\n").replace(
        dependency, dependency.replace("solaris aix", "linux solaris aix")
    )


def main():
    jdk = pathlib.Path(sys.argv[1]) / "jdk"
    native = jdk / "src/solaris/native/sun"
    groups = {
        "xawt/XToolkit.c": ["java_awt_" + name + "_initIDs" for name in (
            "Component", "Container", "Button", "Scrollbar", "Window", "Frame",
            "MenuComponent", "Cursor", "MenuItem", "Menu", "TextArea", "Checkbox",
            "ScrollPane", "TextField", "Dialog", "FileDialog", "KeyboardFocusManager",
            "TrayIcon")],
        "awt/awt_AWTEvent.c": ["java_awt_AWTEvent_initIDs", "java_awt_AWTEvent_nativeSetSource",
                               "java_awt_event_InputEvent_initIDs", "java_awt_event_KeyEvent_initIDs"],
        "awt/awt_Event.c": ["java_awt_Event_initIDs"],
        "awt/awt_Insets.c": ["java_awt_Insets_initIDs"],
        "awt/awt_Font.c": ["java_awt_Font_initIDs"],
        "awt/awt_UNIXToolkit.c": ["sun_awt_SunToolkit_closeSplashScreen"],
    }
    sections = []
    for name, symbols in groups.items():
        source = (native / name).read_text()
        notice_end = source.index("*/") + 2
        sections.append(source[:notice_end])
        sections.extend(extract_function(source, "Java_" + symbol) for symbol in symbols)
    headers = """#include <dlfcn.h>
#include "jni_util.h"
#include "awt_Component.h"
#include "awt_MenuComponent.h"
#include "awt_AWTEvent.h"
#include "awt_Event.h"
#include "awt_Insets.h"
#include "awt_Font.h"

struct ComponentIDs componentIDs;
struct MenuComponentIDs menuComponentIDs;
struct AWTEventIDs awtEventIDs;
struct InputEventIDs inputEventIDs;
struct KeyEventIDs keyEventIDs;
struct EventIDs eventIDs;
struct InsetsIDs insetsIDs;
struct FontIDs fontIDs;
"""
    build = jdk / "make/lib/Awt2dLibraries.gmk"
    text = prepare_build_rules(build.read_text())
    target = native / "xawt/AwtInitIDs.c"
    target.write_text(sections[0] + "\n\n" + headers + "\n\n" + "\n\n".join(sections[1:]) + "\n")
    build.write_text(text)
    print("Prepared X-free AWT JNI initialization from pinned OpenJDK sources")


if __name__ == "__main__":
    main()
