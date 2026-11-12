# 阿里云 OSS 商品图接入

日期：2026-11-12  
Bucket：`qianke-products`  
Region：华南1（深圳）  
Endpoint：`https://oss-cn-shenzhen.aliyuncs.com`

## 状态

```text
代码：已接 OSS 上传 + 删除 + 公网 URL，本地兜底
RAM 用户：qianke-product-uploader
AccessKey：已创建（Secret 不入库、不发聊天）
Bucket 公共读：待确认
.env：待配置
实际 OSS 上传：待凭证配置后验收
```

## RAM 策略

策略名：

```text
QiankeProductImagePolicy
```

资源必须精确到 Bucket：

```json
{
  "Version": "1",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "oss:PutObject",
        "oss:GetObject",
        "oss:DeleteObject"
      ],
      "Resource": [
        "acs:oss:*:*:qianke-products/*"
      ]
    }
  ]
}
```

授权给：

```text
RAM 用户：qianke-product-uploader
```

## Bucket 权限

```text
OSS → qianke-products
→ 权限管理 → 读写权限
→ 公共读
```

商品图需要被 CShop 直接 `<img>` 加载，不能用私有读。

## `.env`

```bash
QIANKE_PRODUCT_MEDIA_BACKEND=oss
QIANKE_PRODUCT_MEDIA_PREFIX=products/

RAG_OSS_BUCKET=qianke-products
RAG_OSS_ACCESS_KEY_ID=...
RAG_OSS_ACCESS_KEY_SECRET=...
RAG_OSS_REGION=cn-shenzhen
RAG_OSS_ENDPOINT=https://oss-cn-shenzhen.aliyuncs.com
RAG_OSS_PREFIX=kb/
```

可选 CDN：

```bash
QIANKE_PRODUCT_MEDIA_BASE_URL=https://cdn.example.com
```

## 上传路径

```text
products/
  m_tea_001/
    P-TEA-003/
      P-TEA-003-<uuid>.webp
      P-TEA-003-<uuid>.thumb.webp
```

返回给 CShop 的 URL：

```text
https://qianke-products.oss-cn-shenzhen.aliyuncs.com/products/...
```

如果配置了 CDN：

```text
https://你的CDN域名/products/...
```

## 删除策略

删除商品图时：

```text
CShop 不再引用
→ 同步删除 OSS 主图
→ 同步删除 OSS 缩略图
→ 写 DELETE 审计
```

删除失败只记日志，不阻断商品记录更新；避免 OSS 抖动导致商家无法管理图片。

## 本地兜底

```bash
QIANKE_PRODUCT_MEDIA_BACKEND=local
```

或 OSS 未配置时：

```text
保存到 var/uploads/products/
CShop 继续使用 /uploads/... URL
```

## 待验证

配置 `.env` 后需要实际跑：

```text
1. B 端上传一张图 → OSS 返回 200
2. 访问 OSS 公共 URL → 200 image/webp
3. CShop 商品卡/详情显示 OSS URL
4. 删除图片 → OSS 对象被删除
5. 审计出现 UPLOAD / DELETE
```

当前未配置真实 AK/SK，因此**不宣称 OSS 上传已通过**。
