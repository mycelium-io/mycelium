import type { OpenClawPluginApi } from "openclaw/plugin-sdk";
import { emptyPluginConfigSchema } from "openclaw/plugin-sdk";
import { myceliumChannelPlugin } from "./src/channel.js";

const plugin = {
  id: "mycelium-channel",
  name: "Mycelium Channel",
  description: "Room-based agent coordination via Mycelium",
  configSchema: emptyPluginConfigSchema(),
  register(api: OpenClawPluginApi) {
    api.registerChannel({ plugin: myceliumChannelPlugin });
    api.logger.info("[mycelium-channel] registered");
  },
};

export default plugin;
