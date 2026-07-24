#!/bin/zsh
# Install the PDF summarizer: CLI command + Finder Quick Action.
#
#   ./install.sh
#
# Safe to re-run; it overwrites the installed copies with this folder's.

emulate -L zsh
set -e

HERE=${0:A:h}
BIN=$HOME/.local/bin
SERVICES=$HOME/Library/Services
WORKFLOW="Summarize PDF with TAMU AI.workflow"

print "Installing from $HERE"

# --- the command -------------------------------------------------------------
mkdir -p $BIN
cp "$HERE/summarize-pdf"     "$BIN/summarize-pdf"
cp "$HERE/summarize_pdf.py"  "$BIN/summarize_pdf.py"
chmod +x "$BIN/summarize-pdf"
print "  ✓ $BIN/summarize-pdf"

# Bundled TAMU AI client, if this checkout has one. Without it the script falls
# back to ~/.claude/skills/tamu-ai/scripts/tamu_ai.py.
if [[ -f "$HERE/tamu_ai.py" ]]; then
    cp "$HERE/tamu_ai.py" "$BIN/tamu_ai.py"
    print "  ✓ $BIN/tamu_ai.py"
elif [[ ! -f "$HOME/.claude/skills/tamu-ai/scripts/tamu_ai.py" ]]; then
    print "  ! No tamu_ai.py here and none in ~/.claude/skills/tamu-ai/scripts/."
    print "    The summarizer cannot reach TAMU AI without it. See the README."
fi

# --- the Finder Quick Action -------------------------------------------------
if [[ -d "$HERE/$WORKFLOW" ]]; then
    mkdir -p $SERVICES
    rm -rf "$SERVICES/$WORKFLOW"
    cp -R "$HERE/$WORKFLOW" "$SERVICES/$WORKFLOW"
    # Finder does not show a new Service until the pasteboard server rescans.
    /System/Library/CoreServices/pbs -update 2>/dev/null || true
    print "  ✓ $SERVICES/$WORKFLOW"
fi

# --- checks ------------------------------------------------------------------
print ""
if [[ :$PATH: != *:$BIN:* ]]; then
    print "  ! $BIN is not on your PATH. Add this to ~/.zshrc:"
    print "      export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

if [[ -z ${TAMU_AI_API_KEY:-} && ! -f $HOME/.config/tamu-ai/api-key ]]; then
    print "  ! No TAMU AI API key found. Get one from chat.tamu.ai -> Settings"
    print "    -> API Key, then add to ~/.zshenv (NOT ~/.zprofile -- Automator"
    print "    does not read that):"
    print "      export TAMU_AI_API_KEY='sk-...'"
    print "    Then: chmod 600 ~/.zshenv"
fi

print "Done. Try:  summarize-pdf yourpaper.pdf"
print "Or right-click a PDF in Finder -> Quick Actions."
