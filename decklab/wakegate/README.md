# Deck Lab's wake gate

The Deck Lab PC goes to sleep when nobody has used Deck Lab for a while (`wake.idle_minutes` in `decklab/config.json`). The wake gate wakes it again whenever someone opens Deck Lab. It runs on an always-on box on the home network: here the Asustor NAS, in Docker.

- **At home**, phones and laptops open `http://<nas address>:8650` (bookmark it). If the PC is awake, the gate sends the browser straight on to Deck Lab on the PC. If it's asleep, the gate sends a Wake-on-LAN "magic packet" and shows **Deck Lab is waking up**. That page opens Deck Lab by itself once the PC answers, usually in under a minute. After 3 minutes (`WAKE_TIMEOUT`) it says the PC couldn't be woken and offers **Try again**.
- **From outside**, people still go to `https://decklab.example.com`. While the PC sleeps, its Cloudflare Tunnel is down, so the Deck Lab Worker (`decklab/cloudflare/`) answers instead. It asks the gate to wake the PC through a second, small tunnel that runs on the NAS (`wake.decklab.example.com`), and Cloudflare Access only lets the Worker's service token through that tunnel. Through Cloudflare the gate answers only `POST /__wake`. Everything else is 404, so nobody outside can learn anything about the home network.

The files in this folder:

| File | What it is |
|---|---|
| `wakegate.py` | The gate itself: one Python script, standard library only (Python 3.9 or later) |
| `compose.yaml` | The Docker stack: `wakegate` (the script in a `python` Alpine image) and `cloudflared` (the NAS tunnel); both images are pinned to exact versions there, and Dependabot proposes newer ones once a month |
| `.env.example` | The settings to copy into `.env` |

## The gate's answers

The HTTP server holds at most 32 accepted connections and closes an idle/stalled
socket after 10 seconds. Extra connections are closed before another handler
thread is created; closing or timing out releases capacity. These are connection
limits, not a new wake rate or permission rule.

The wakegate container runs as UID/GID 65534 with a read-only root, every capability
dropped and no-new-privileges. Python bytecode writes are disabled. Its bind-mounted
public `wakegate.py` must be readable by that UID; do not widen permissions on `.env`
or tunnel tokens. Qualify the updated stack on the actual NAS, including a real
wake packet, before calling that deployment accepted. Source tests use fake WOL
and disposable loopback sockets; no actual NAS setup was performed by the coding task.

| Request | Answer |
|---|---|
| `GET /__status` | `200 {"awake": true/false, "waking": true/false, "since": seconds or null, "pc": "http://DECKLAB_PC_HOST:DECKLAB_PC_PORT"}` (`since` is how long ago this wake attempt's first packet went; `pc` is the exact address the gate redirects to, port included). It carries `Access-Control-Allow-Origin` set to that same address and `Vary: Origin`, so only Deck Lab's own page on the PC can read it from another address |
| `POST /__wake` | `202 {"sent": true/false, "retry_after": seconds}`. It sends at most one packet every `WAKE_MIN_INTERVAL` seconds (30) |
| `GET` any other path | If the PC answers, a `302` redirect to `http://DECKLAB_PC_HOST:DECKLAB_PC_PORT` with the same path and query. Otherwise it sends a packet and shows the waking page |

The redirect is built only from the configured PC address, never from the request's `Host` header. A request target that isn't a plain `/path` gets `400`. The gate logs one line for each packet it sends and each error (`docker logs`), and nothing for ordinary requests.

## 1. Get the PC ready to be woken

1. **Wake-on-LAN on.** In the PC's BIOS/UEFI, turn on Wake-on-LAN (it may be called "Power on by PCI-E" or "Resume by LAN"). In Windows, open Device Manager, then the network adapter's Properties. On the **Power Management** tab, tick **Allow this device to wake the computer** and **Only allow a magic packet to wake the computer**. On **Advanced**, set **Wake on Magic Packet** to Enabled.
2. **Use a cable.** Wake-on-LAN is reliable only over Ethernet. Most Wi-Fi adapters can't be woken from sleep.
3. **The PC's MAC address.** Run `ipconfig /all` on the PC and read the wired adapter's **Physical Address**, such as `AA-BB-CC-DD-EE-FF`. You can also run `getmac /v`. Either `aa:bb:cc:dd:ee:ff` or `aa-bb-cc-dd-ee-ff` works in `.env` (the example `aa:bb:cc:dd:ee:ff` itself is refused, so a copied example never goes unnoticed).
4. **A fixed address.** In the router, give the PC a DHCP reservation (static lease) so `DECKLAB_PC_HOST` stays the same. Use that reserved IP address as the setting, such as `192.168.1.20`, not a `.local` name: the container can't resolve `.local` names.
5. **One address for Deck Lab at home.** `DECKLAB_PC_HOST` should be the address people open Deck Lab by at home, and they should open it through the gate's bookmark (`http://<nas address>:8650`). Deck Lab's page only sends people through the gate when it was opened from exactly `http://DECKLAB_PC_HOST:DECKLAB_PC_PORT`, because a browser keeps the chosen profile and editor drafts separately for each address: opened by another name, the PC's page would land people on a different address with none of them.
6. **Wake timers on.** So the nightly backup can wake the PC, allow wake timers on AC power: **Control Panel > Power Options > Change plan settings > Change advanced power settings > Sleep > Allow wake timers: Enable**, or from an administrator prompt:

   ```
   powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1
   powercfg /setactive SCHEME_CURRENT
   ```

### A Linux PC

Steps 2, 4 and 5 are the same. In place of steps 1, 3 and 6:

1. **Wake-on-LAN on, at every boot.** Turn it on in the BIOS/UEFI as above. Then keep the adapter armed, since Linux turns it off again at each boot: with netplan (Ubuntu Server's default), a file of its own such as `/etc/netplan/60-wake-on-lan.yaml` matching the adapter by MAC address, with `set-name` and `wakeonlan: true`, then `sudo netplan generate` (SELF-HOSTING.md, step 12, has the whole file); with NetworkManager, `sudo nmcli connection modify <connection> 802-3-ethernet.wake-on-lan magic` (`nmcli connection show` lists the connections); with systemd-networkd alone, a `.link` file for the adapter with `WakeOnLan=magic` (never beside netplan's own `.link` file). `sudo ethtool <adapter>` should show `Wake-on: g`.
2. **Deep sleep.** `cat /sys/power/mem_sleep` should show `[deep]`. If it shows `[s2idle]`, add `mem_sleep_default=deep` to the kernel command line (in `/etc/default/grub`, then `sudo update-grub`), or the magic packet may not wake it.
3. **The PC's MAC address.** `ip link` shows it as `link/ether aa:bb:cc:dd:ee:ff` under the wired adapter.
4. **Sleeping when idle.** A Linux PC with no desktop never suspends by itself: as root, write `/etc/systemd/logind.conf.d/decklab.conf` with `[Login]`, `IdleAction=suspend` and `IdleActionSec=10min`, then restart the PC. Deck Lab holds it awake while in use with `systemd-inhibit`; if polkit refuses that, SELF-HOSTING.md step 12 has the rule that allows it.
5. **Wake for the nightly backup.** A user timer can't wake the PC. `python -m decklab.db schedule wake-timer` prints the `sudo` commands that install a system timer waking it a minute before 03:30; Deck Lab never installs it itself.
6. **Check:** `python -m decklab.lib.homenet status` has Wake lines for `mem_sleep`, the adapter, the wake timer and the gate.

## 2. Run the gate on the Asustor

1. In ADM's **App Central**, install **Docker Engine**, then **Portainer** or **Dockge**. Either one runs the stack.
2. Copy this folder (`wakegate.py`, `compose.yaml`, `.env.example`) to the NAS, for example to `/volume1/Docker/wakegate/`. With Dockge, put it in Dockge's stacks folder as a stack named `wakegate`.
3. Copy `.env.example` to `.env` in the same folder. Fill in `DECKLAB_PC_MAC` and `DECKLAB_PC_HOST` (both required: the stack won't deploy while either is blank), and leave `COMPOSE_PROFILES` and `TUNNEL_TOKEN` for step 3 below. `.env` will hold a secret: keep it on the NAS and never commit it.
4. Deploy the stack. This first deploy starts only the gate: the NAS tunnel (`cloudflared`) is in the `tunnel` profile, which stays off until step 3.
   - **Dockge:** open the `wakegate` stack and press **Deploy**. Dockge reads `.env` from the stack's folder, and `./wakegate.py` stays a relative path.
   - **Portainer:** go to **Stacks**, then **Add stack**, and paste `compose.yaml` into the web editor. A relative path in a web-editor stack resolves inside Portainer's own data folder, not the folder you copied, so change the volume line to the file's absolute path on the NAS, such as `/volume1/Docker/wakegate/wakegate.py:/app/wakegate.py:ro`. Enter the settings in the stack's **Environment variables** section (Portainer doesn't read the copied `.env`).

   Both containers use the host's network (`network_mode: host`), so the packet's broadcast reaches the home network and the gate listens on the NAS's own port 8650.
5. Bookmark `http://<nas address>:8650` on the household's phones and laptops: that's how Deck Lab is opened at home from now on.
6. Later, for visitors from outside (step 3 below), set `TUNNEL_TOKEN` and `COMPOSE_PROFILES=tunnel` (uncomment it in `.env`, or add both in Portainer's Environment variables) and deploy again: the tunnel then starts beside the gate.

Check it from any computer at home:

```
curl http://<nas address>:8650/__status
curl -X POST http://<nas address>:8650/__wake
```

The first command should say `"awake": true` while the PC is on. Put the PC to sleep, then run the second command: the PC should wake within a few seconds, and the container's log should show `wakegate: wake packet sent to ...`. If the PC doesn't wake, set `WOL_BROADCAST` to your network's broadcast address (such as `192.168.1.255`) and check step 1 again.

## 3. The Cloudflare side (visitors from outside)

1. In **Cloudflare Zero Trust**, go to **Networks**, then **Tunnels**, and create a tunnel for the NAS (Cloudflared type). Copy its token from the Docker install command into `.env` as `TUNNEL_TOKEN`, set `COMPOSE_PROFILES=tunnel`, and deploy the stack again (step 2.6).
2. Give that tunnel a **public hostname**: `wake.decklab.example.com` → service `http://localhost:8650`.
3. Under **Access**, go to **Service auth** and create a **service token**, for example `decklab-worker`. Copy its Client ID and Client Secret. The secret is shown only once. **Note the token's expiry date**: when it expires, the Worker can no longer wake the PC, so renew it before then and set the new values in step 5.
4. Under **Access**, go to **Applications** and add a self-hosted application on `wake.decklab.example.com`. Give it one policy with the action **Service Auth** that includes only that service token. Visitors' browsers never go there, so it needs no email login.
5. From `decklab/cloudflare/`, give the Worker the address and the token:

   ```
   npx wrangler secret put WAKE_URL            # https://wake.decklab.example.com/__wake
   npx wrangler secret put WAKE_CLIENT_ID      # the service token's Client ID
   npx wrangler secret put WAKE_CLIENT_SECRET  # the service token's Client Secret
   ```

   While `WAKE_URL` is unset, the Worker shows **Deck Lab is off** exactly as before. Once it's set, the Worker's pages say Deck Lab is waking up and ask the gate for a wake.

To check the public side, try `curl -X POST https://wake.decklab.example.com/__wake` without the token. Access should refuse it. With `-H "CF-Access-Client-Id: ..." -H "CF-Access-Client-Secret: ..."` it should answer `202`. A `GET https://wake.decklab.example.com/__status`, even with the token, answers 404.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `DECKLAB_PC_MAC` | (required) | The PC's wired network card |
| `DECKLAB_PC_HOST` | (required) | The PC's reserved IP address on the home network, the address people open Deck Lab by at home |
| `COMPOSE_PROFILES` | (unset) | `tunnel` starts the NAS tunnel beside the gate (compose only, not the gate) |
| `TUNNEL_TOKEN` | (blank) | The NAS tunnel's token (compose only, not the gate) |
| `DECKLAB_PC_PORT` | `8642` | Deck Lab's port on the PC |
| `GATE_PORT` | `8650` | The gate's port on the NAS |
| `WOL_BROADCAST` | `255.255.255.255` | Where the magic packet is broadcast |
| `WOL_PORT` | `9` | The packet's UDP port |
| `WAKE_MIN_INTERVAL` | `30` | The fewest seconds between two packets |
| `WAKE_TIMEOUT` | `180` | How long the waking page waits before it says the PC couldn't be woken |

If a setting is wrong, the gate stops at once (exit code 2) and its log says which setting. A PC counts as awake when `GET /api/status` on it answers within 2 seconds with `200` or with Deck Lab's `X-Deck-Lab-Origin` header. The gate sends that check with `X-Deck-Lab-Poll: 1`, so its checks don't keep the PC awake.

Tests: `python scripts/test_fixtures.py decklab.tests.test_wakegate` (no packet is ever sent).
