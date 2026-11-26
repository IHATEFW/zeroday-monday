# Política de privacidad — Zero-Day Monday

*Última actualización: 25 de noviembre de 2026*

Zero-Day Monday es una herramienta personal y de código abierto que publica un post semanal en **mi propia cuenta de LinkedIn**. No es un servicio para terceros: la única persona que la autoriza y la usa soy yo, el dueño de este repositorio.

## Qué datos usa
- **Token de acceso de LinkedIn y mi identificador de miembro (URN):** se obtienen con OAuth (permisos `openid`, `profile` y `w_member_social`) y se usan solo para publicar posts, subir la imagen del post y agregar un comentario en mi propio perfil.
- **Mi nombre de perfil:** se lee una vez durante la autorización para confirmar qué cuenta se conectó. No se guarda.

## Qué NO hace
- No lee, recopila ni almacena datos de otros usuarios de LinkedIn (contactos, mensajes, reacciones, comentarios ni perfiles).
- No vende, comparte ni transfiere datos a terceros.
- No usa cookies ni rastreo de ningún tipo.

## Dónde se guardan los datos
El token y el URN se guardan cifrados como *GitHub Actions Secrets* de este repositorio y nunca se escriben en el código ni en el historial. El token vence a los 60 días y puede revocarse en cualquier momento desde LinkedIn: **Configuración → Privacidad de datos → Otras aplicaciones**.

## Contenido publicado
Los posts se generan a partir de noticias públicas de seguridad informática. Cada post publicado queda registrado en `posts/` y `data/history.json` dentro de este repositorio.

## Contacto
Para cualquier consulta, abre un issue en este repositorio: https://github.com/IHATEFW/zeroday-monday/issues

---

*English summary: Zero-Day Monday is a personal, open-source tool that posts only to its owner's own LinkedIn account. It uses the owner's OAuth token solely to create posts, upload the post image and add a comment. It does not collect data from any other LinkedIn member, does not share data with third parties, and stores credentials only as encrypted GitHub Actions secrets.*
