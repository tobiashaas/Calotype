--[[ Tarsier — Lightroom Classic plugin.

The plugin is the user interface; all network work happens in the Tarsier Bridge
(a local app on 127.0.0.1, see docs/adr/004-bridge-localhost-architecture.md).
UI texts use Lightroom's LOC mechanism: English defaults here, German in
TranslatedStrings_de.txt (picked automatically when Lightroom runs in German).
]]

return {
  LrSdkVersion = 10.0,
  LrSdkMinimumVersion = 6.0,

  LrToolkitIdentifier = "photo.tarsier.lightroom",
  LrPluginName = "Tarsier",
  LrPluginInfoUrl = "https://github.com/tobiashaas/tarsier",

  -- Starts the (opt-in) automation channel for end-to-end tests, see Automation.lua.
  LrInitPlugin = "Automation.lua",
  -- Without this Lightroom loads the plugin only on first use, so the automation
  -- channel would not start with Lightroom.
  LrForceInitPlugin = true,

  -- Library > Plug-in Extras
  LrLibraryMenuItems = {
    { title = LOC "$$$/Tarsier/Menu/Train=Train profile from selected photos...", file = "TrainProfile.lua" },
    { title = LOC "$$$/Tarsier/Menu/Apply=Apply profile to selected photos...", file = "ApplyProfile.lua" },
    { title = LOC "$$$/Tarsier/Menu/Cull=Sort selected photos (culling)...", file = "CullPhotos.lua" },
    { title = LOC "$$$/Tarsier/Menu/Status=Bridge status...", file = "BridgeStatus.lua" },
  },

  -- File > Plug-in Extras
  LrExportMenuItems = {
    { title = LOC "$$$/Tarsier/Menu/TrainFile=Tarsier: Train profile...", file = "TrainProfile.lua" },
    { title = LOC "$$$/Tarsier/Menu/ApplyFile=Tarsier: Apply profile...", file = "ApplyProfile.lua" },
    { title = LOC "$$$/Tarsier/Menu/CullFile=Tarsier: Sort photos (culling)...", file = "CullPhotos.lua" },
    { title = LOC "$$$/Tarsier/Menu/StatusFile=Tarsier: Bridge status...", file = "BridgeStatus.lua" },
  },

  VERSION = { major = 0, minor = 3, revision = 0 },
}
