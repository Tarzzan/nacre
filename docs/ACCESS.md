# Accès de partout

Deuxième brique de l’espace collaboratif : se connecter en sécurité ailleurs que sur la machine elle-même. Elle arrive en trois temps ; ce guide grandit avec eux.

| Temps | Contenu | État |
| --- | --- | --- |
| Double authentification | Un code du téléphone en plus du mot de passe | Depuis 0.8.0-alpha.55 |
| Accès par le réseau | Écoute en HTTPS, noms d’hôte reconnus | À venir |
| Téléphone | Interface adaptée, installation sur l’écran d’accueil | À venir |

## Double authentification

Chaque personne l’active pour son propre compte, quel que soit son rôle. Une fois active, un code à six chiffres donné par une application d’authentification est demandé à chaque connexion par mot de passe.

### Activer

1. **Mon compte → Double authentification** : saisir son mot de passe actuel.
2. Scanner le **code QR** avec l’application d’authentification du téléphone, ou saisir la clé affichée.
3. Saisir le code à six chiffres que l’application affiche : la double authentification n’est active qu’après ce premier code juste.
4. **Noter les dix codes de secours** et les ranger hors du NAS. Ils ne sont affichés qu’une fois.

![Activation de la double authentification](images/totp-setup.jpg)

*Banc local : compte fictif, clé jetée au lancement suivant.*

### Se connecter

L’identifiant et le mot de passe d’abord ; le champ du code n’apparaît que si le compte en demande un. Un code de secours se saisit dans le même champ et ne sert qu’une fois.

### À savoir

- **Compatible avec les applications courantes** : norme TOTP (RFC 6238), six chiffres, trente secondes. Le téléphone doit être à l’heure ; la période précédente et la suivante sont tolérées.
- **Un code ne sert qu’une fois** : le même code rejoué dans sa demi-minute est refusé.
- **Activer ferme les autres sessions** du compte.
- **Désactiver** demande le mot de passe et un code, du téléphone ou de secours.
- **Téléphone et codes perdus** : un administrateur retire la double authentification d’une autre personne dans **Personnes et espaces** ; ses sessions sont fermées et le geste est au journal. Pour son propre compte, il reste le lien de connexion locale.
- **Le lien de connexion locale ne demande pas de code.** Il se génère sur la machine elle-même, par quelqu’un qui en a déjà la maîtrise : c’est le recours, pas une porte dérobée du réseau.
- **Ce qui est gardé** : la clé, dans la base privée de la console, car elle est nécessaire pour vérifier les codes ; les codes de secours sous forme d’empreinte seulement.
- **Les tentatives sont limitées** à huit par minute, mot de passe et code confondus.

### Limites

- **Pas d’obligation par rôle** : un administrateur ne peut pas encore l’imposer aux autres.
- **Pas de clé matérielle** (FIDO2, WebAuthn).
- **Le code QR est dessiné par la console**, sans service extérieur ; il a été comparé module à module à une bibliothèque de référence sur 96 cas.
