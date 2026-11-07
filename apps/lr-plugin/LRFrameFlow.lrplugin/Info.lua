--[[ LR-FrameFlow — Lightroom Classic plugin.

The plugin is the user interface; all network work happens in the LR-FrameFlow Bridge
(a local app on 127.0.0.1, see docs/adr/004-bridge-localhost-architecture.md).
UI texts use Lightroom's LOC mechanism: English defaults here, German in
TranslatedStrings_de.txt (picked automatically when Lightroom runs in German).
]]

return {
  LrSdkVersion = 10.0,
  LrSdkMinimumVersion = 6.0,

  LrToolkitIdentifier = "io.github.lrframeflow",
  LrPluginName = "LR-FrameFlow",
  LrPluginInfoUrl = "https://github.com/tobiashaas/LR-FrameFlow",

  -- Starts the (opt-in) automation channel for end-to-end tests, see Automation.lua.
  LrInitPlugin = "Automation.lua",

  -- Library > Plug-in Extras
  LrLibraryMenuItems = {
    { title = LOC "$$$/LRFrameFlow/Menu/Train=Train profile from selected photos...", file = "TrainProfile.lua" },
    { title = LOC "$$$/LRFrameFlow/Menu/Apply=Apply profile to selected photos...", file = "ApplyProfile.lua" },
    { title = LOC "$$$/LRFrameFlow/Menu/Status=Bridge status...", file = "BridgeStatus.lua" },
  },

  -- File > Plug-in Extras
  LrExportMenuItems = {
    { title = LOC "$$$/LRFrameFlow/Menu/TrainFile=LR-FrameFlow: Train profile...", file = "TrainProfile.lua" },
    { title = LOC "$$$/LRFrameFlow/Menu/ApplyFile=LR-FrameFlow: Apply profile...", file = "ApplyProfile.lua" },
    { title = LOC "$$$/LRFrameFlow/Menu/StatusFile=LR-FrameFlow: Bridge status...", file = "BridgeStatus.lua" },
  },

  VERSION = { major = 0, minor = 2, revision = 0 },
}
