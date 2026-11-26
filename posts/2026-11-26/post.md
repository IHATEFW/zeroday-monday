Sin credenciales, cualquiera con red hacia tu vCenter entra como administrator@vsphere.local. Y ya se usó como 0-day.

Es el CVE-2026-123890, un bypass de autenticación en VMware Directory Service (vmdir). Tiene CVSS 9.8 y está en KEV desde el 20/11.

GTIG y Mandiant lo atribuyen a ARMORY CASTLE, un actor sospechoso de nexo con China, que lo explota desde inicios de septiembre.

El bug: vmdir entrega sin autenticar la clave de sesión SRP-6a por DCE/RPC. Con eso armas una sesión de admin SSO y te quedas con los ESXi y las VMs.

Ojo, que no necesita exposición a internet. En la intrusión documentada entraron por otro appliance y pivotaron al vCenter desde adentro.

Además, lo vieron funcionar en un vCenter ya parchado contra el bypass de vmdir de julio.

🛠️ Hoy haría esto:
- Parchar a 8.0 U3m, 9.0.2.0200, 9.1.1.0200 o VCF 5.2.5. No hay workaround. En 7.0 no hay build pública.
- Restringir el acceso de red al appliance y mandar sus logs al SIEM.
- Buscar compromiso previo, porque el parche no saca a quien ya entró.

📡 También en el radar
- NGINX: dos RCE pre-auth en HTTP/2 (CVE-2026-123633 y CVE-2026-123007). Si todavía no parchas, apaga HTTP/2.
- Unos agentes de IA encontraron y explotaron un 0-day en MONAI Label (CVE-2026-133968) en unos 11 minutos.

¿Desde cuántos segmentos de tu red se llega hoy al vCenter?

#VMware #RedTeam #ZeroDay

---
**Primer comentario:**

Fuentes:

vCenter CVE-2026-123890 (Horizon3.ai): https://horizon3.ai/attack-research/vulnerabilities/cve-2026-123890/
NVD: https://nvd.nist.gov/vuln/detail/CVE-2026-123890
Análisis de Rapid7 (SRP bypass a root): https://www.rapid7.com/blog/post/ra-rapid7-analysis-vmware-vcenter-srp-authentication-bypass-to-root-cve-2026-123890
Rapid7 sobre el nuevo CVE-2026-123903: https://www.rapid7.com/blog/post/etr-cve-2026-123903-critical-vmware-directory-service-authentication-bypass-affects-vcenter
The Hacker News (KEV y Armory Castle): https://thehackernews.com/2026/11/hackers-exploit-critical-vmware-cisco.html

NGINX HTTP/2 (Wiz): https://www.wiz.io/blog/nginx-http2-rce-vulnerabilities
NGINX (Rapid7): https://www.rapid7.com/blog/post/ve-cve-2026-123007-critical-nginx-http-2-integer-underflow-leads-to-rce-fixed

MONAI Label y el ataque con agentes de IA: https://nvd.nist.gov/vuln/detail/CVE-2026-133968 | https://thehackernews.com/2026/11/hackers-exploit-n-able-mailassure-flaw.html
