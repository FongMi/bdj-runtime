# Source provenance and third-party notices

This repository is a clean export of the BD-J build utilities. It does not
contain private Media history, credentials, upstream port shell scripts or
Lucida fonts. Source archive hashes and original URLs are recorded in
`sources.json`; the original per-file notices remain in the preserved archives.

- OpenJDK: `jdk8u482-ga`, revision
  `cea3cd4c1d7aa70e998d45ca2e419793a550321e`, from OpenJDK `jdk8u`.
  GPLv2, with the Classpath exception on designated files and additional
  third-party notices in its `THIRD_PARTY_README`.
- Android compatibility patch collection: preserved from
  `AngelAuraMC/angelauramc-openjdk-build`, revision
  `f03a5a05d76394bc3e91317e9ff4b8c21e5cb802`, based on OpenJDK Android/mobile
  and PojavLauncher adaptations. The archive retains the original patch bytes
  and source notices. This collection has several licenses: OpenJDK GPLv2 and
  designated Classpath exceptions, glibc LGPL2.1+, AOSP per-file Apache/BSD,
  Nuxi BSD2 and J.T. Conklin public-domain `search.h`. Included ICU headers are
  version 57.1; its full original IBM/Google license is included separately.
- FreeType 2.10.4: dual FTL/GPLv2 licensing. The GPLv2 option is used for the
  runtime linked with OpenJDK. Its original `docs/LICENSE.TXT`, `FTL.TXT` and
  `GPLv2.TXT` remain in the source archive.
- libffi 3.4.8: MIT license; original `LICENSE` remains in its source archive.
- CUPS 2.2.4: original GPLv2/LGPLv2 with Apple exceptions. The build uses its
  headers; original license files remain in the source archive.
- DejaVu 2.37: original Bitstream/Arev font licenses and public-domain DejaVu
  changes. Both complete source and TTF archives are preserved. The font input
  packages 12 original faces and includes the original full license, per-face
  hashes and logical Java family mappings. It does not rename fonts to Lucida.
- NDK r10e: official Google toolchain download, verified with a pinned SHA-256.
  The toolchain is not republished as a source archive. Its component licenses
  accompany the official download.

The runtime's native source adaptations and generated AWT source retain the
upstream notices. Corresponding full sources, local modifications, font sources
and the exact recipe commit are available with every build's provenance.
