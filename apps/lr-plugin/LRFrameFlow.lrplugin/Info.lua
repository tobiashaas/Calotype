--[[ LR-FrameFlow — Lightroom Classic plugin.

The plugin is the user interface; all network work happens in the LR-FrameFlow Bridge
(a local app on 127.0.0.1, see docs/adr/004-bridge-localhost-architecture.md).
]]

return {
  LrSdkVersion = 10.0,
  LrSdkMinimumVersion = 6.0,

  LrToolkitIdentifier = "io.github.lrframeflow",
  LrPluginName = "LR-FrameFlow",
  LrPluginInfoUrl = "https://github.com/tobiashaas/LR-FrameFlow",

  -- Library > Plug-in Extras
  LrLibraryMenuItems = {
    { title = "Train profile from selected photos...", file = "TrainProfile.lua" },
    { title = "Apply profile to selected photos...", file = "ApplyProfile.lua" },
    { title = "Bridge status...", file = "BridgeStatus.lua" },
  },

  -- File > Plug-in Extras
  LrExportMenuItems = {
    { title = "LR-FrameFlow: Train profile...", file = "TrainProfile.lua" },
    { title = "LR-FrameFlow: Apply profile...", file = "ApplyProfile.lua" },
    { title = "LR-FrameFlow: Bridge status...", file = "BridgeStatus.lua" },
  },

  VERSION = { major = 0, minor = 1, revision = 0 },
}
