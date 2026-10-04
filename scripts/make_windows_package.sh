#!/bin/bash
# 打包 Windows 安装包（含你的 backend/.env 密钥），输出 dist-windows/StockPanel-Windows.zip
# 生成的 zip 含密钥：只通过私聊发给家人，不要上传到任何公开位置（dist-windows/ 已被 .gitignore 忽略）。
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/dist-windows"
NAME="StockPanel-Windows"
STAGE="$OUT/$NAME"

[ -f "$ROOT/backend/.env" ] || { echo "错误: 没有 backend/.env，无法打包密钥" >&2; exit 1; }

rm -rf "$STAGE" "$OUT/$NAME.zip"
mkdir -p "$STAGE"

# Windows 脚本统一 CRLF（cmd 对 LF 换行的 .bat 解析不可靠）
for f in install.bat install.ps1; do
  perl -pe 's/\r?\n/\r\n/' "$ROOT/scripts/windows/$f" > "$STAGE/$f"
done
cp "$ROOT/backend/.env" "$STAGE/stockpanel.env"

# 说明文件: UTF-8 BOM + CRLF，记事本直接打开不乱码
{
  printf '\xef\xbb\xbf'
  perl -pe 's/\r?\n/\r\n/' <<'TXT'
StockPanel 股票分析 - 安装说明
================================

第一次安装（只做一次）:
  1. 先把整个压缩包“解压”到桌面（右键 → 全部解压缩），不要直接在压缩包里双击。
  2. 打开解压出来的文件夹，双击 install.bat。
     如果弹出“Windows 已保护你的电脑”，点“更多信息” → “仍要运行”。
     如果弹出“是否允许此应用更改设备”，点“是”。
  3. 等待几分钟，装完会自动打开浏览器，桌面上也会出现“StockPanel 股票分析”图标。

以后每次使用:
  双击桌面上的“StockPanel 股票分析”图标即可，会自动更新到最新版本。
  用完直接关闭那个黑色窗口。

注意: 本文件夹里的 stockpanel.env 是密钥，请不要发给别人。安装完成后可以删除整个文件夹。
TXT
} > "$STAGE/README.txt"

(cd "$OUT" && zip -qr "$NAME.zip" "$NAME")
rm -rf "$STAGE"
echo "已生成: $OUT/$NAME.zip"
