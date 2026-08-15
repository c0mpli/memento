"""Known apps: browsers (AppleScript tab access) and the daily work-app set.

Bundle ids let us pick the best capture method per app. This list is data, not
logic — add an app here and the orchestrator handles it.
"""

from __future__ import annotations

# Chromium/WebKit browsers we can ask for the active tab's URL + title.
BROWSERS = {
    "com.google.Chrome": "Google Chrome",
    "com.google.Chrome.canary": "Google Chrome Canary",
    "com.brave.Browser": "Brave Browser",
    "com.microsoft.edgemac": "Microsoft Edge",
    "com.vivaldi.Vivaldi": "Vivaldi",
    "company.thebrowser.Browser": "Arc",
    "app.zen-browser.zen": "Zen",
    "ai.perplexity.comet": "Comet",
    "com.pushplaylabs.sidekick": "Sidekick",
    "com.operasoftware.Opera": "Opera",
}
# WebKit browsers use `current tab` instead of `active tab`.
SAFARI_FAMILY = {
    "com.apple.Safari": "Safari",
    "com.apple.SafariTechnologyPreview": "Safari Technology Preview",
    "com.kagi.kagimacOS": "Orion",
}

# Daily work apps whose focused-window Accessibility text is worth extracting.
# category is informational; presence here just marks "prefer AX text".
WORK_APPS = {
    "com.tinyspeck.slackmacgap": ("Slack", "chat"),
    "com.microsoft.teams2": ("Microsoft Teams", "chat"),
    "com.microsoft.teams": ("Microsoft Teams", "chat"),
    "com.hnc.Discord": ("Discord", "chat"),
    "net.whatsapp.WhatsApp": ("WhatsApp", "chat"),
    "org.telegram.desktop": ("Telegram", "chat"),
    "ru.keepcoder.Telegram": ("Telegram", "chat"),
    "com.apple.mail": ("Mail", "email"),
    "com.microsoft.Outlook": ("Outlook", "email"),
    "com.readdle.smartemail-Mac": ("Spark", "email"),
    "notion.id": ("Notion", "docs"),
    "md.obsidian": ("Obsidian", "docs"),
    "com.apple.Notes": ("Notes", "docs"),
    "com.microsoft.Word": ("Word", "docs"),
    "com.apple.iWork.Pages": ("Pages", "docs"),
    "com.linear": ("Linear", "tasks"),
    "com.culturedcode.ThingsMac": ("Things", "tasks"),
    "com.todoist.mac.Todoist": ("Todoist", "tasks"),
    "com.omnigroup.OmniFocus3": ("OmniFocus", "tasks"),
    "com.apple.iCal": ("Calendar", "calendar"),
    "com.flexibits.fantastical2.mac": ("Fantastical", "calendar"),
    "com.microsoft.VSCode": ("VS Code", "dev"),
    "com.todesktop.230313mzl4w4u92": ("Cursor", "dev"),
    "com.apple.Terminal": ("Terminal", "dev"),
    "com.googlecode.iterm2": ("iTerm", "dev"),
    "com.jetbrains.intellij": ("IntelliJ", "dev"),
    "us.zoom.xos": ("Zoom", "meeting"),
}


def is_browser(bundle: str) -> bool:
    return bundle in BROWSERS or bundle in SAFARI_FAMILY


def is_webkit(bundle: str) -> bool:
    return bundle in SAFARI_FAMILY


def is_work_app(bundle: str) -> bool:
    return bundle in WORK_APPS
