# Mihena


Application de bureau Windows pour compresser et extraire des fichiers BZIP2, LZMA/XZ et des archives 7z. L’interface permet aussi d’inspecter le contenu d’une archive, de rechercher des entrées et d’en extraire une sélection.

Le logiciel s’appuie sur les codecs de Python (`bz2`, `lzma`) et la bibliothèque `py7zr`. Il ne réimplémente pas les algorithmes de compression.

## Fonctionnalités

- Compresser un ou plusieurs fichiers en `.bz2`, `.xz` ou `.lzma`.
- Utiliser par défaut le niveau de compression maximal, avec un dictionnaire LZMA de 32 Mio ; ces réglages augmentent le temps de calcul et la mémoire utilisée.
- Créer une archive `.7z` à partir de fichiers et de dossiers, avec niveau LZMA2 et mot de passe facultatif.
- Décompresser les flux `.bz2`, `.xz`, `.lzma` et extraire des archives `.7z`.
- Explorer, rechercher et extraire une sélection de fichiers d’une archive 7z.
- Afficher l’arborescence d’une archive, trier ses colonnes et accéder aux actions utiles par clic droit.
- Voir les tailles réelles, le taux de réduction mesuré et la durée des opérations.
- Afficher l’avancement des flux par octets traités et annuler aux points sûrs.
- Utiliser un accueil simple avec deux actions principales, une navigation latérale, le glisser-déposer et les thèmes clair, sombre ou automatique.
- Garder les réglages avancés repliés tant qu’ils ne sont pas nécessaires ; consulter l’historique dans son écran dédié.
- Utiliser les raccourcis `Ctrl+O` (ouvrir une archive), `Ctrl+Entrée` (lancer) et `Échap` (demander l’annulation).
- Consulter l’historique et modifier les limites de sécurité.
- Refuser l’écrasement par défaut, demander confirmation avant remplacement à l’extraction, traiter les fichiers par blocs et nettoyer les sorties temporaires en cas d’échec.
- Vérifier les chemins des archives, refuser les chemins absolus, les traversées `..` et les liens symboliques, avec des limites de nombre d’éléments et de taille décompressée.

Les mots de passe ne sont jamais enregistrés dans l’historique. Les fichiers extraits ne sont jamais exécutés automatiquement. Les formats déjà compressés (JPEG, MP4, ZIP, PDF, etc.) peuvent toutefois gagner très peu, même avec l’intensité maximale.

## Prérequis et installation

- Windows 10/11 et Python 3.10 ou ultérieur.
- Tkinter, normalement fourni avec Python pour Windows.
- `py7zr` 1.1 ou ultérieur pour les archives 7z (validation réalisée avec 1.1.4).
- `tkinterdnd2` 0.6.4 ou ultérieur pour le glisser-déposer natif.

Depuis le dossier du projet :

```powershell
python -m pip install -r requirements.txt
```

## Lancer l’application

Double-cliquez sur `Demarrer.pyw`. Pour lancer depuis PowerShell :

```powershell
python -m compress_clone gui
```

La ligne de commande reste disponible, mais n’est pas nécessaire à l’usage normal de l’application :

```powershell
python -m compress_clone compress .\document.txt --format bz2
python -m compress_clone decompress .\document.txt.bz2 --output .\document-restaure.txt
python -m compress_clone list .\archive.7z
```

Pour `.bz2`, `.xz` et `.lzma`, plusieurs fichiers sélectionnés produisent un flux compressé chacun. Un dossier entier se compresse en `.7z`.

## Tests

Installer la dépendance de développement et exécuter les tests :

```powershell
python -m pip install -e ".[dev]"
python -m pytest
```

Les tests couvrent les formats flux, les images, dossiers et fichiers vides ou volumineux, les noms accentués, les mots de passe 7z, l’intégrité après extraction, les collisions, les erreurs d’accès, l’annulation, les archives corrompues et la traversée de chemins.

## Créer l’installateur Windows

Sur l’ordinateur qui sert à préparer la distribution, installez [Inno Setup 6](https://jrsoftware.org/isinfo.php), puis lancez :

```powershell
.\packaging\build_windows.ps1
```

Le script crée un environnement de construction isolé, installe les dépendances nécessaires à la compilation et produit `dist\installer\Mihena-Setup.exe`. Cet installateur contient Python, l’application et ses bibliothèques : sur l’ordinateur destinataire, il suffit d’ouvrir le fichier et de cliquer sur **Installer**. Python et `requirements.txt` n’y sont pas nécessaires.

L’installation est proposée pour le compte Windows courant. Le raccourci du menu Démarrer est créé automatiquement; la création d’un raccourci sur le Bureau est proposée en option. Vérifiez l’installateur sur un ordinateur Windows propre avant distribution, notamment les fonctions 7z et glisser-déposer.

## Limites connues

- Aucun exécutable 7-Zip/7zz n’est présent dans l’environnement actuel ; `py7zr` fournit le support 7z. L’application détecte et affiche la présence d’un moteur externe.
- `py7zr` ne prend pas en charge toutes les fonctions de l’application 7-Zip. Les archives multiparties, certaines options avancées de solidité et certaines méthodes propriétaires ne sont pas exposées dans cette version.
- La progression de création 7z est mise à jour entre les éléments ajoutés ; le moteur ne fournit pas de progression fiable à l’intérieur d’un seul gros fichier. L’annulation d’une écriture 7z est donc prise en compte entre les éléments. Les flux BZIP2/LZMA s’annulent entre blocs.
- `py7zr` rapporte la progression d’extraction, mais n’interrompt pas un bloc de décompression en cours. Une annulation 7z est donc appliquée avant extraction ou après l’étape en cours, avant la validation des fichiers temporaires. Les métadonnées affichées dépendent de celles présentes dans l’archive.
- Le glisser-déposer est géré par `tkinterdnd2` ; les sélecteurs Windows restent disponibles en complément.
- Les opérations LZMA utilisent XZ (`.xz`) ou le conteneur LZMA seul (`.lzma`). Une archive 7z peut utiliser LZMA2.

