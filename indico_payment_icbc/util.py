import base64

from Crypto.Cipher import AES
from Crypto.Hash import MD5, SHA256
from Crypto.PublicKey import RSA
from Crypto.Signature import PKCS1_v1_5
from Crypto.Util.Padding import pad


class RsaUtil(object):
    def __init__(
        self,
        *,
        private_key=None,
        public_key=None,
        private_key_file=None,
        public_key_file=None,
        private_key_password=None,
    ):
        self.private_key = RsaUtil.import_key(
            key=private_key,
            key_file_path=private_key_file,
            passphrase=private_key_password,
        )
        if (
            public_key is None
            and public_key_file is None
            and self.private_key is not None
        ):
            self.public_key = self.private_key.publickey()
        else:
            self.public_key = RsaUtil.import_key(
                key=public_key, key_file_path=public_key_file
            )

    def create_sign(self, encrypt_str):
        """
        私钥加签
        :return:
        """
        hash_obj = SHA256.new(encrypt_str.encode(encoding="utf-8"))
        # 改用PKCS1_v1_5
        return base64.b64encode(PKCS1_v1_5.new(self.private_key).sign(hash_obj)).decode(
            encoding="utf-8"
        )

    def verify_sign(self, encrypt_str, signature):
        """
        公钥验签
        :param encrypt_str:
        :param signature:
        :return:
        """
        hash_obj = MD5.new(encrypt_str.encode(encoding="utf-8"))
        decode_sign = base64.b64decode(signature)
        # print(f'decode sign {decode_sign}')

        try:
            # 改用PKCS1_v1_5
            PKCS1_v1_5.new(self.public_key).verify(hash_obj, decode_sign)
        except (ValueError, TypeError) as e:
            print(f"signature invalid, error {e}")
            return False
        return True

    @staticmethod
    def aes_encrypt(to_encrypt: str, key: str) -> str:
        # 将Base64编码的密钥解码为字节
        key_bytes = base64.b64decode(key)
        # 将明文转换为UTF-8编码的字节
        plaintext_bytes = to_encrypt.encode("utf-8")
        # 创建全零的IV（16字节）
        iv = bytes([0] * 16)
        # 创建AES-CBC cipher实例，使用PKCS7填充
        cipher = AES.new(key_bytes, AES.MODE_CBC, iv=iv)
        # 对明文进行PKCS7填充
        padded_plaintext = pad(plaintext_bytes, AES.block_size, style="pkcs7")
        # 执行加密
        ciphertext = cipher.encrypt(padded_plaintext)
        # 返回Base64编码的密文
        return base64.b64encode(ciphertext).decode("utf-8")

    @staticmethod
    def encrypt_str(path, params):
        """
        参数拼接
        :param params:
        :return:
        """
        return f'{path}?{"&".join([f"{k}={v}" for k, v in dict(sorted(params.items())).items()])}'

    @staticmethod
    def import_key(*, key=None, key_file_path=None, passphrase=None):
        """
        导入key
        :return:
        """
        if key is not None:
            return RSA.import_key(key, passphrase=passphrase)
        elif key_file_path is not None:
            return RSA.import_key(open(key_file_path).read(), passphrase=passphrase)
        else:
            return None

    @staticmethod
    def create_rsa_key(password):
        """
        生成密钥对
        :return:
        """
        key = RSA.generate(2048)
        encrypt_key = key.exportKey(
            passphrase=password, pkcs=8, protection="scryptAndAES128-CBC"
        )
        with open("my_private_rsa_key.pem", "wb") as f:
            f.write(encrypt_key)

        with open("my_rsa_public.pem", "wb") as f:
            f.write(key.publickey().exportKey())


if __name__ == "__main__":
    RsaUtil.create_rsa_key("123456")
    rsa_util = RsaUtil(private_key_password="123456")
    params = {"name": "张三", "sex": "男", "score": 86}
    encrypt_str = rsa_util.encrypt_str("", params)
    print(f"encrypt_str {encrypt_str}")
    # 签名
    signature = rsa_util.create_sign(encrypt_str)
    print(f"signature {signature}")
    # 平台签名示例签名结果
    signature = "E2s8Ma7l7JMK1t4ClitZxY/1sZO2WIVw+qsPppumMV4aCqgHYoXv8gGSockMfcPt03w0FWZPot4J79iOL1f3LgJ+etEV8hUZfMl+MkGsL2Sy5nP9olQYBKxH2mZjUNBfIIktGRwwscASJhW+3AcIKXcPynBqPJDPkgQgfw91uqvkSq0aGeUj4Jji4MRYZR7e2w3ztxyFAVJvRNa3wILjDECUfZo6aUx29ndqndKUX+mdgLyLSGCbv+Iz06ScYenCfjfscMcc8jWRT2aRvyuGhXd4tlStErCSai9TGxXwq5G02l1H4ubOtbr19ii0aOfYE2ua6V0ovl5JQy4o8wCHAA=="
    # 验签
    is_passed = rsa_util.verify_sign(encrypt_str, signature)
    print(f"is passed {is_passed}")
