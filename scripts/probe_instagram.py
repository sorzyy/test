"""Sonde Instagram : page embed et miroirs publics, pour un shortcode donné."""

import re
import sys

import httpx

UA_BOT = "Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)"
UA_TG = "TelegramBot (like TwitterBot)"
MIRRORS = ["kkinstagram.com", "vxinstagram.com", "instagramez.com", "ddinstagram.com", "eeinstagram.com",
           "uuinstagram.com", "d.vxinstagram.com", "g.ddinstagram.com", "toinstagram.com"]


def meta(html: str, prop: str) -> list[str]:
    pat = r'<meta[^>]+(?:property|name)="%s"[^>]+content="([^"]+)"' % re.escape(prop)
    pat2 = r'<meta[^>]+content="([^"]+)"[^>]+(?:property|name)="%s"' % re.escape(prop)
    return re.findall(pat, html) + re.findall(pat2, html)


def main(code: str, kind: str = "reel") -> None:
    with httpx.Client(follow_redirects=True, timeout=20) as c:
        r = c.get(f"https://www.instagram.com/p/{code}/embed/captioned/",
                  headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/140.0 Safari/537.36"})
        h = r.text
        print(f"embed: {r.status_code} len={len(h)} video_url={'video_url' in h} display_url={'display_url' in h} "
              f"contextJSON={'contextJSON' in h} gql_data={'gql_data' in h} EmbeddedMediaImage={'EmbeddedMediaImage' in h}")
        for m in re.findall(r'.{80}video_url.{160}', h)[:2]:
            print("   ", m)
        for host in MIRRORS:
            for ua in (UA_BOT, UA_TG):
                try:
                    r = c.get(f"https://www.{host}/{kind}/{code}/", headers={"User-Agent": ua})
                    vids, imgs = meta(r.text, "og:video") + meta(r.text, "og:video:secure_url"), meta(r.text, "og:image")
                    print(f"{host} [{ua[:12]}] {r.status_code} final={str(r.url)[:80]} og:video={vids[:1]} og:image={imgs[:1]}")
                    if vids:
                        v = c.get(vids[0].replace("&amp;", "&"), headers={"User-Agent": ua})
                        print(f"   -> video fetch {v.status_code} {v.headers.get('content-type')} {len(v.content)} octets "
                              f"final={str(v.url)[:90]}")
                        break
                except Exception as exc:
                    print(f"{host} [{ua[:12]}] ERREUR {type(exc).__name__}: {str(exc)[:120]}")


if __name__ == "__main__":
    main(*sys.argv[1:])
