# 随站点托管的第三方脚本

网站不依赖外部 CDN 加载核心展示脚本。这里的文件原样保存，更新时按下列方式重新核验。

| 文件 | 版本 | 来源 | 许可 | SHA-512（SRI） |
|---|---|---|---|---|
| `chart.umd.min.js` | Chart.js 4.4.1 | https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js | MIT（`LICENSE.chartjs.md`） | `sha512-CQBWl4fJHWbryGE+Pc7UAxWMUMNMWzWxF4SQo9CgkJIN1kx6djDQZjh3Y8SZ1d+6I+1zze6Z7kHXO7q3UyZAWw==` |

2026-10-23 下载，与 cdnjs API 公布的 SRI 值一致（`https://api.cdnjs.com/libraries/Chart.js/4.4.1?fields=sri`）。测试 `tests/test_site.py` 会校验文件的 SHA-512。
