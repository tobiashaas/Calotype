--[[ Calotype — Lightroom Classic plugin.

The plugin is the user interface; all network work happens in the Calotype Bridge
(a local app on 127.0.0.1, see docs/adr/004-bridge-localhost-architecture.md).
UI texts use Lightroom's LOC mechanism: English defaults here, German in
TranslatedStrings_de.txt (picked automatically when Lightroom runs in German).
]]

return {
  LrSdkVersion = 10.0,
  LrSdkMinimumVersion = 6.0,

  LrToolkitIdentifier = "xyz.calotype.lightroom",
  LrPluginName = "Calotype",
  LrPluginInfoUrl = "https://github.com/tobiashaas/calotype",

  -- Starts the (opt-in) automation channel for end-to-end tests, see Automation.lua.
  LrInitPlugin = "Automation.lua",
  -- Without this Lightroom loads the plugin only on first use, so the automation
  -- channel would not start with Lightroom.
  LrForceInitPlugin = true,

  -- Library > Plug-in Extras
  LrLibraryMenuItems = {
    { title = LOC "$$$/Calotype/Menu/Train=Train profile from selected photos...", file = "TrainProfile.lua" },
    { title = LOC "$$$/Calotype/Menu/Apply=Apply profile to selected photos...", file = "ApplyProfile.lua" },
    { title = LOC "$$$/Calotype/Menu/Cull=Sort selected photos (culling)...", file = "CullPhotos.lua" },
    { title = LOC "$$$/Calotype/Menu/Status=Bridge status...", file = "BridgeStatus.lua" },
  },

  -- File > Plug-in Extras
  LrExportMenuItems = {
    { title = LOC "$$$/Calotype/Menu/TrainFile=Calotype: Train profile...", file = "TrainProfile.lua" },
    { title = LOC "$$$/Calotype/Menu/ApplyFile=Calotype: Apply profile...", file = "ApplyProfile.lua" },
    { title = LOC "$$$/Calotype/Menu/CullFile=Calotype: Sort photos (culling)...", file = "CullPhotos.lua" },
    { title = LOC "$$$/Calotype/Menu/StatusFile=Calotype: Bridge status...", file = "BridgeStatus.lua" },
  },

  VERSION = { major = 0, minor = 3, revision = 0 },
}
