# 3x-ui-nosponsor

Builds of [3x-ui](https://github.com/MHSanaei/3x-ui) with the sponsored content removed, as Docker images and as native (systemd) release tarballs. Everything else is unchanged upstream code.

A scheduled GitHub Action checks for a new upstream release every 3 hours. When it finds one, it applies [`remove-sponsors.py`](remove-sponsors.py) and builds upstream's own `Dockerfile` for each platform in parallel on a native runner (ARM images on GitHub's ARM runners, no emulation). Each platform's image is tested on its own architecture before anything is tagged. Then the images are published and a matching [release](../../releases) is created.

## Usage

```bash
docker run -d --name 3x-ui --restart unless-stopped --network host \
  -v $PWD/db:/etc/x-ui \
  -v $PWD/cert:/root/cert \
  ghcr.io/ggyasin/3x-ui:latest
```

The image is also published to Docker Hub as `ggyasin/3x-ui`. Tags:

| Tag | Meaning |
|---|---|
| `latest` | Newest upstream release |
| `3.10.0`, `v3.10.0` | A specific upstream release |
| `3.10` | Newest patch release of that minor version |

Platforms: `linux/amd64`, `linux/arm64`, `linux/arm/v7`, `linux/arm/v6`, `linux/386`.

Configuration, ports and volumes are the same as the [upstream Docker setup](https://github.com/MHSanaei/3x-ui). The panel listens on port `2053`.

## Native install (systemd)

The releases also carry `x-ui-linux-<arch>.tar.gz` in upstream's exact layout, plus `install.sh`, `update.sh` and `x-ui.sh` that download from this repo instead of upstream.

Switch an existing 3x-ui install to this build. It keeps the database, inbounds, clients and settings, and restarts x-ui:

```bash
bash <(curl -Ls https://github.com/ggYasin/3x-ui-nosponsor/releases/latest/download/update.sh)
```

Fresh install:

```bash
bash <(curl -Ls https://github.com/ggYasin/3x-ui-nosponsor/releases/latest/download/install.sh)
```

From then on, the panel's **Update** button, its "new version" notice and `x-ui update` all use this repo's releases, so an update can't bring the sponsors back. The rolling `dev` channel isn't published here, so a dev update fails instead of installing upstream's build.

## What is removed, and how it stays removed

The script works in layers, from the most generic (survives upstream rewrites) to the most specific:

1. **DNS guard.** A small Go package ([`overlay/internal/nosponsor`](overlay/internal/nosponsor/nosponsor.go)) is compiled into the panel. It refuses DNS lookups for `sanaei.dev` and all of its subdomains. Any feed, logo or fallback upstream adds later can't be fetched, whatever code tries to fetch it. Xray traffic is not affected.
2. **URL scrub.** Every `*.sanaei.dev` host in the code is rewritten to an unresolvable `.invalid` host. The only exceptions are the plain Docs and Donate links.
3. **Component kill.** Every UI component in a file whose path mentions sponsor, advert or promo renders nothing. This includes components added in future versions.
4. **Known code.** The sponsor API always returns an empty list. The Sponsors page is removed from the menu, routes and command palette.
5. **Updates.** The panel's updater and version check, and the install/update scripts, download from this repo's releases instead of upstream's.

Each build is checked before it is published:

- The script **fails the build** if upstream changes something it can't recognise. A release is skipped rather than shipped with ads.
- The DNS guard has its own tests, which run in the workflow.
- Every platform's image is pulled back by digest and started on its own architecture. `/sponsors` must return an empty list, and the compiled binary must contain no `sanaei.dev` hosts except the Docs and Donate links.
- Nothing is tagged until all platforms pass. After tagging, every tag is checked for all 5 platforms, and both registries are checked for anonymous pull access.
- Each native tarball must contain exactly the same files as upstream's tarball for that version. Its static binary is started on its own architecture and gets the same checks. Neither the binary nor the scripts may download from upstream.
- The release is created as a pre-release first. It's installed fresh with its own `install.sh`, then updated with its own `update.sh`, on real amd64 and arm64 VMs. Only then is it marked as the latest release, which is what panels' Update button follows.
- Upstream commits and files since the previous release that mention sponsors, ads, promos or banners are listed in the job summary and the release notes for a human to review.

The exact source diff of each build is attached to its release as `nosponsor-<version>.diff`.

## Manual runs

**Actions → Build → Run workflow** builds the latest release, or any upstream tag you enter. Tick *force* to rebuild a version that was already released.

## License

GPL-3.0, the same as upstream. 3x-ui is © its authors. This repo only contains the build automation and the patch script.
