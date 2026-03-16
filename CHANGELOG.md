# Changelog

## [0.7.2](https://github.com/iloveitaly/git-history-extraction/compare/v0.7.1...v0.7.2) (2026-03-16)


### Bug Fixes

* Update README by removing development and requirements ([cc7e5f9](https://github.com/iloveitaly/git-history-extraction/commit/cc7e5f99a952b237bbd317af29668fb8b4059dca))

## [0.7.1](https://github.com/iloveitaly/git-history-extraction/compare/v0.7.0...v0.7.1) (2026-03-16)


### Bug Fixes

* migrate to toon-format dependency and update imports ([6568b66](https://github.com/iloveitaly/git-history-extraction/commit/6568b66c6f39484a54a298dae1c6daf4c52d10d1))

## [0.7.0](https://github.com/iloveitaly/git-history-extraction/compare/v0.6.0...v0.7.0) (2026-01-19)


### Features

* add remote option to use upstream/default branch in cli ([2c25c9c](https://github.com/iloveitaly/git-history-extraction/commit/2c25c9cd9060c2e69bfc9b4958c569dc47af7ab3))


### Bug Fixes

* correct --since-last-tag logic and update docs/tests ([e95b7c2](https://github.com/iloveitaly/git-history-extraction/commit/e95b7c205eb4be83d83608abc69aa9e6dc84908e))

## [0.6.0](https://github.com/iloveitaly/git-history-extraction/compare/v0.5.0...v0.6.0) (2026-01-16)


### Features

* extract commits between last two version tags via cli ([aab79d3](https://github.com/iloveitaly/git-history-extraction/commit/aab79d32126b8c92ac9fbdb6b7e465bb8febc41a))


### Documentation

* remove outdated dev structure and testing section from README ([1cbfc6a](https://github.com/iloveitaly/git-history-extraction/commit/1cbfc6ab8401c4ba7fd634baa2ae7776c2aeab5a))

## [0.5.0](https://github.com/iloveitaly/git-history-extraction/compare/v0.4.0...v0.5.0) (2025-11-24)


### Features

* add verbose logging with structlog-config ([#18](https://github.com/iloveitaly/git-history-extraction/issues/18)) ([e95bad4](https://github.com/iloveitaly/git-history-extraction/commit/e95bad4293b5a1db17be5f95b9c11e297e52b3cb))


### Bug Fixes

* remove py 3.10 ([c0ec43e](https://github.com/iloveitaly/git-history-extraction/commit/c0ec43ed515bb9c4ca72d4de6db7b53c77aa04ed))

## [0.4.0](https://github.com/iloveitaly/git-history-extraction/compare/v0.3.0...v0.4.0) (2025-11-18)


### Features

* add --version flag to CLI ([#10](https://github.com/iloveitaly/git-history-extraction/issues/10)) ([7758361](https://github.com/iloveitaly/git-history-extraction/commit/7758361a352b993c7846bb2a53e71e13934702ac))
* add TOON format export option ([#12](https://github.com/iloveitaly/git-history-extraction/issues/12)) ([c38a436](https://github.com/iloveitaly/git-history-extraction/commit/c38a43685f2683a0f889a8944fe766c08eaa520f))
* fix logic for --since-last-tag to correctly handle 0 as LatestTag..HEAD and 1 as PreviousTag..LatestTag
* allow numeric --since-last-tag to skip N most recent tags ([#13](https://github.com/iloveitaly/git-history-extraction/issues/13)) ([3e6834b](https://github.com/iloveitaly/git-history-extraction/commit/3e6834b2550913cb43952687e3d0648cb281ef80))


### Bug Fixes

* handle single line commit ([#9](https://github.com/iloveitaly/git-history-extraction/issues/9)) ([4ab6ee5](https://github.com/iloveitaly/git-history-extraction/commit/4ab6ee52d279f47e3418e45317802ce7c95e96e5))

## [0.3.0](https://github.com/iloveitaly/git-history-extraction/compare/v0.2.0...v0.3.0) (2025-11-12)


### Features

* Add git history extraction header output ([#7](https://github.com/iloveitaly/git-history-extraction/issues/7)) ([edeb861](https://github.com/iloveitaly/git-history-extraction/commit/edeb86189bc8c8081d2fb14cd1860ae21ade5990))
* add git repository validation with clear error message ([#4](https://github.com/iloveitaly/git-history-extraction/issues/4)) ([efb12b4](https://github.com/iloveitaly/git-history-extraction/commit/efb12b4c049af2c7d7289469c06adc5b1019b92c))

## [0.2.0](https://github.com/iloveitaly/git-history-extraction/compare/v0.1.0...v0.2.0) (2025-11-01)


### Features

* add since-last-tag and last Monday history options ([781f356](https://github.com/iloveitaly/git-history-extraction/commit/781f3566a9cfae4b448e8609ebcf340c8bc21742))

## 0.1.0 (2025-10-31)


### Features

* add commit-based log filtering and debug output in main.py ([39daa18](https://github.com/iloveitaly/git-history-extraction/commit/39daa18440b6d43bc2b1dfd3886a39d0712c6582))
* include committed files in get_git_commits output ([1185994](https://github.com/iloveitaly/git-history-extraction/commit/1185994fac5c9607aa53d2f632cba0893e9df3e2))
* initialize project structure and config files ([a8dc734](https://github.com/iloveitaly/git-history-extraction/commit/a8dc7345e4f23ff02ff1d06ffddb043b48ca8419))
* **playground:** add summarize_commits.py and update main.py output options ([7c1ebff](https://github.com/iloveitaly/git-history-extraction/commit/7c1ebffe6cd462eadb675e68d53da6f4c460be64))
* refactor main.py for click CLI, trailers and repo path support ([fe1f5e0](https://github.com/iloveitaly/git-history-extraction/commit/fe1f5e0af3f52eb060dc0803e155ec17aebe3a4a))


### Documentation

* add AI commit prompt for structured git trailers in readme ([2f54c07](https://github.com/iloveitaly/git-history-extraction/commit/2f54c07c4e603f392dd2c3f9c68ecf58434249b9))
* add new rules and prompts for coding and tests ([db64cf6](https://github.com/iloveitaly/git-history-extraction/commit/db64cf633beb7b841dea1a5d0b02b7cd5b3ccdc0))
* add README for git-summarize-activity usage and options ([dd1bf02](https://github.com/iloveitaly/git-history-extraction/commit/dd1bf0258f2f7aed8c0f9836cd091cb1f4629113))
* clarify AI summarization workflow and expand keywords ([f636eca](https://github.com/iloveitaly/git-history-extraction/commit/f636ecad76e49aca0b1fada470679f2eb6f99e3f))
* clarify AI usage for git history summarization in README ([bc32be2](https://github.com/iloveitaly/git-history-extraction/commit/bc32be29e2dfc3f66adc726d40752884060a6104))
* update README with new tool features and usage instructions ([94ad8b6](https://github.com/iloveitaly/git-history-extraction/commit/94ad8b6fe2ff1803605d25b518301be45d699634))
