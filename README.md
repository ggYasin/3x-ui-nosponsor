# 3x-ui-nosponsor

Docker images of [3x-ui](https://github.com/MHSanaei/3x-ui) with the sponsored content removed. Everything else is unchanged upstream code.

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

## What is removed, and how it stays removed

The script works in layers, from the most generic (survives upstream rewrites) to the most specific:

1. **DNS guard.** A small Go package ([`overlay/internal/nosponsor`](overlay/internal/nosponsor/nosponsor.go)) is compiled into the panel. It refuses DNS lookups for `sanaei.dev` and all of its subdomains. Any feed, logo or fallback upstream adds later can't be fetched, whatever code tries to fetch it. Xray traffic is not affected.
2. **URL scrub.** Every `*.sanaei.dev` host in the code is rewritten to an unresolvable `.invalid` host. The only exceptions are the plain Docs and Donate links.
3. **Component kill.** Every UI component in a file whose path mentions sponsor, advert or promo renders nothing. This includes components added in future versions.
4. **Known code.** The sponsor API always returns an empty list. The Sponsors page is removed from the menu, routes and command palette.

Each build is checked before it is published:

- The script **fails the build** if upstream changes something it can't recognise. A release is skipped rather than shipped with ads.
- The DNS guard has its own tests, which run in the workflow.
- Every platform's image is pulled back by digest and started on its own architecture. `/sponsors` must return an empty list, and the compiled binary must contain no `sanaei.dev` hosts except the Docs and Donate links.
- Nothing is tagged until all platforms pass. After tagging, every tag is checked for all 5 platforms, and both registries are checked for anonymous pull access.
- Upstream commits and files since the previous release that mention sponsors, ads, promos or banners are listed in the job summary and the release notes for a human to review.

The exact source diff of each build is attached to its release as `nosponsor-<version>.diff`.

## Manual runs

**Actions → Build → Run workflow** builds the latest release, or any upstream tag you enter. Tick *force* to rebuild a version that was already released.

## License

GPL-3.0, the same as upstream. 3x-ui is © its authors. This repo only contains the build automation and the patch script.
