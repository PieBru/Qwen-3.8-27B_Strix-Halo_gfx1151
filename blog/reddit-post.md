# Reddit post — r/LocalLLaMA (also fits r/AMDMachines, r/MiniPCs, r/selfhosted)

**Suggested title:** I made a €2,000 mini-PC run a 27-billion-parameter AI brain 24/7, fully offline — and the biggest surprise was how cheap a huge context window got

**Body:**

Hi! We tuned a small AMD mini-PC to run a big "thinking" AI model entirely by itself — no cloud, no API keys, no bills. Every number below was measured on our desk, and everything we learned lives in one GitHub repo. Here's the story, explained simply.

## The machine

A GMKtec EVO-X2 mini-PC with an AMD Strix Halo chip (Ryzen AI MAX+ 395). No graphics card at all — the CPU and the small built-in GPU share 128 GB of RAM like two kids sharing one giant pizza. Cost: about €2,000. Power use: ~85 W at full speed, roughly one old lightbulb. It sits on the desk, quietly, and never phones home.

## What runs on it

A 27-billion-parameter reasoning model (Qwen3.8-27B, unsloth dynamic GGUFs) served by llama.cpp built for Vulkan. Reading speed (prefill): ~330 tokens/s. Writing speed (decode): ~29 tokens/s in the default setup, ~32 in speed mode. Fast enough to chat with, and to let an AI agent work on your code all day.

## The three tricks, explained like you're twelve

**1. Shrunk copies (quantization).** The same model comes in different file sizes: Q8 is the fat, faithful copy, Q6 is the sensible default, Q5 is the light one. Like WAV versus MP3 — a smaller file loses a tiny bit of quality. We measured exactly how much (perplexity and KL-divergence, in the repo), so picking a size is picking a price, not a guess.

**2. The fast friend (speculative decoding).** Next to the big model runs a tiny fast one (the DFlash2 draft, ~2 GB). The small one guesses the next few words, then the big one checks all the guesses at once. Right guesses = several words written for the price of one check. That's where our 29–32 tokens/s comes from.

**3. The magic notebook (why huge context is nearly free here).** Most models remember the chat in a memory pile that grows as they read — the more you feed them, the slower every new word gets. This model is a hybrid: most of its layers keep a fixed-size notebook instead of a growing pile. So we turned the context window from 32k up to 256k tokens and the speed barely moved (28–30 t/s). The window became a dial you turn per request — you pay RAM (~45 → 61 GiB), not speed.

## The recipe menu

One port serves everything. Say which recipe you want in the request, like ordering a pizza size:

- `Qwen38-27B-quality` — Q8, the careful one, window up to 256k
- `Qwen38-27B-balanced` — Q6, the daily driver (loaded at boot so it's ready before you ask)
- `Qwen38-27B-speed` — Q5, the fastest writer
- `Qwen38-27B-vision` — the one that can look at pictures

There's also a nickname, plain `Qwen38-27B`, that always points at your favorite recipe. Change your mind about the default? Move one line in the config file and every client, script and box on the LAN follows the move without any changes.

## Traps we fell into (so you don't have to)

- A harmless-looking `repeat_penalty` made the fast-friend trick much worse: −23–28% speed, because the big model stopped agreeing with its draft. We serve without it.
- The smallest copy (Q4) was **slower** than Q5 — quant noise makes the big model reject more draft guesses, and the rejections eat the whole win.
- Two recipes resident at once means two full copies of the weights in RAM, even from the same file. We cap it at one resident model.
- The Vulkan driver crashes if you fill the context really deep (≥128k positions in one go). Big windows still work fine for normal use; just don't paste a whole 200k-token book in one message.
- Vision works, but images and the fast friend don't mix yet — the vision recipe drops speculative decode (8.4 vs 29 t/s for the same weights).

## Try it on your own Strix Halo box

Any mini-PC or desktop with the same AMD chip works. About 45 minutes, headless, no desktop environment needed:

```bash
git clone https://github.com/PieBru/Qwen-3.8-27B_Strix-Halo_gfx1151
cd Qwen-3.8-27B_Strix-Halo_gfx1151
# install deps, build the Vulkan fork, download ~73 GiB of models —
# exact commands in the README, plus a downloader that checksum-verifies everything
./run_llama-server.sh --router --port 8080
```

That gives you every recipe on one port, with the default preloaded and a nickname that never breaks your clients.

The repo README is the full map: benchmark tables, every trap with its evidence, a 1M-context investigation (spoiler: 262k is the servable ceiling today), power measurements, and the systemd setup for running it as a boot service on two boxes. Clone it, measure on your own hardware, and tell us where your numbers disagree — that's how this thing got honest.

Link: **https://github.com/PieBru/Qwen-3.8-27B_Strix-Halo_gfx1151**
