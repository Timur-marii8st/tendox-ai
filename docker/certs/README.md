# Доверенный корень ЕИС

`russian-trusted-root-ca.crt` получен 2026-09-28 по HTTPS с официального
ресурса Госуслуг `https://gu-st.ru/content/Other/doc/russian_trusted_root_ca.cer`;
страница установки: https://www.gosuslugi.ru/crt. Приведён к PEM.

- DER SHA-256 сертификата: `d26d2d0231b7c39f92cc738512ba54103519e4405d68b5bd703e9788ca8ecf31`.
- SHA-256 PEM-файла: `aa800ef345422d6158c6fafe1c06c429dbda21c3df4bb1ccb45a920ec1111399`.
- Subject/issuer: `Russian Trusted Root CA`, Минцифры, RU.
- Срок: до 2032-02-27. Публичный сертификат, не ключ и не токен.

Образ API/worker добавляет этот корень в системное и Chromium NSS хранилища;
хостовые ОС не изменяются. HTTPS validation остаётся включённой. Замена
сертификата требует нового официального источника и сверки SHA.
