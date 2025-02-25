import requests

data = {}
data["app_id"] = "11000000000000048026"
data["msg_id"] = "20250224052721"
data["charset"] = "UTF-8"
data["encrypt_type"] = "AES"
data["sign"] = (
    "grQ+jLjdQULcsU3TaSSwLaBIajXduZYT4AZBHvIwjfXrnwTGJNomcrx483659LtuRF15RCtqpIPnuiSdOI5zkuHDfYaDf433mhPkYArBfNQZl4EozzA2XjY05+bvAmMMNTy0CkW+tRjyGM+A6s8WMGQyGxoNlPGqNpFdJdxevtor9BXsUmjPmymm2kaj0oiFfcbC0gT2c2Ss5RQa5upTZ5pt94uIe6n0K7004qQqu+R0zrtaABOx3SX/mCbtsMeNeuQFmCI6/M1OIM6NaCQM7e9Gsx8iHIc/Q+d4KgBRpnTFFsfrCVMpS+Nr6sO5tI88zuEglXyjyuN3OajKiXfqLg=="
)
data["sign_type"] = "RSA2"
data["timestamp"] = "2025-02-24 05:36:26"
data["biz_content"] = (
    "2pXxh8MBoyaNB8nLPdkRa5dZkDK5uJRd9Kig8XFd2Xyzj0+N1bC730qaD+lq7N3AC96+MIRYZK0gXvrRl/GYXVMlwapmG76BgJgj8jPEgMXEaP50cIOkDK5NlMweMtbaUFE3Nxa6mZT+6ndwQ2jHIo6bnXSgxzz0RAX7rtXQZozZo/kEXOEBtfyhVjJzVU1RCRZ2B2n8Kd6yPaTrrsHumeImRJGu8uhL9OxOSpi+o+kUJ187Hv3s3L2qMAiv6x3KA2gPYjG9mVU9YDLdq0jB3YMV1PXrcx/DnN9N9H+UNAQRoa6MprIMsiPbgcO1jiKgcLPA+4jgJGNbstPFlBahnN7J89wjxRMXpneGEX/+7IyUPv489uKgTtzYCp+hA/elJMvmdXVdZyP0moMKvDzZsatLP8vXYKBIv+CIZSfz57L5r3cL9S2ZHdK6v1EmfkXJwdb5dwxUKgZBy/PjVEG9B4r1MFDcxrjhW91DQ49OYXUfyqRIlJEC3vMpWchefriVFmpe8M7eQ1qEJaRm4UQhqZKi/nOFp1Pjg3nFK1BnozdXag212/9RVe4WhUXPeumhOw3gQP2IA+eQARZlJMjV9JGZ0k39poTu5ieqhiYU1SgXsc3ylsj0NO3/D1ziioZxto7AxS2Tyj73cRh5gP9F4c1HjS7ja/z8m2BuJX+DFYQ35uaQWITfd6WHrXlztYN666udrgAfoaHPwoZNB5Q6RQ0xv92DCmkrO2JkKRqnVAFbrhFgQBCJp6qtBtPPbFQtGDd66X0sbF4xbsl4bnDAx8jwgIhlQORechrU3N6pExt/8gOb2JjPMCGSVSuY9hdW"
)

print(data)

url = "https://gw.open.icbc.com.cn/ui/cardbusiness/epaypc/consumption/V1"

response = requests.post(url, data=data)

response.encoding = "uft-8"
print(response.text)
