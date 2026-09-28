# The range starts at the deployed SHA

The range is `<production deployment sha>..<default branch>`, taken from the deployments API, rather than from the
production deployment's tag or from project badges. A deployment's ref need not be a tag (a hotfix branch, a manual
redeploy), and badges are set by pipelines that can drift from what was deployed; the deployed SHA is the one value
that names exactly what production runs. The cost is that a service with no successful production deployment has no
range at all and reports a warning instead of guessing one from its newest tag.
