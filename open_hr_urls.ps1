$urls = @(
    "https://www.facebook.com/watch?ref=saved&v=738622082558442",
    "https://www.facebook.com/hunterrootmusic/posts/pfbid0eUv1dz1hrNzCbG2oW3woyYt1uQzqj1qfiVR93N8XVYbU2C7kaFN8eGF1UtBMjaTml",
    "https://theticketing.co/e/hunterrootlive",
    "https://www.facebook.com/watch?ref=saved&v=810914703992548",
    "https://www.facebook.com/events/792245497101970/",
    "https://www.facebook.com/watch?ref=saved&v=246491528309184",
    "https://www.facebook.com/watch?ref=saved&v=638495335160946",
    "https://www.facebook.com/hunterrootmusic/posts/pfbid0LidJG1qscTbaRVsmUbDpz1UD2bbeoremaGREt3P2v2yoftPw5LuJeYmrp4BSnBMl",
    "https://www.facebook.com/watch?ref=saved&v=934622031119101",
    "https://www.facebook.com/hunterrootmusic/posts/pfbid0txdYb4XiFENjb5de3tYGczQLLyacvWmJpkdAcBqTZ1313yFN7E2jAYd56jXC6nmnl",
    "https://www.facebook.com/watch?ref=saved&v=868526517906088",
    "https://www.facebook.com/hunter.root.7/posts/pfbid02ivYJCrXtSjzTPkxgykQUtwZ8EBeJn814eKRV1WMUhd4ctac52aym5G9ydQgRPvjSI",
    "https://www.facebook.com/hunter.root.7/posts/pfbid02mZDTvx1iTu98rHEMSAd8Dhh3kjL884tHze93TZcQDcgPVnx8MTge5M9mTbD7YuenI",
    "https://www.facebook.com/hunter.root.7/posts/pfbid02rTANf7xr4eaZJ31nLJogxYZFCTK7Gu4cLf6FKdwyE27Gg9rDhpTjPJsEw5wggmywI",
    "https://www.facebook.com/hunter.root.7/posts/pfbid0ESX7zKZGRroRmui2tfioH8BJ7uXWuiRK838ZM5EP1RY85JEeEKRgrH86zQ4PaqCmI",
    "https://www.facebook.com/photo.php?fbid=4248737508494080&set=a.826187380749127&type=3",
    "https://www.facebook.com/events/477375978963567/",
    "https://www.facebook.com/watch?ref=saved&v=1887755838800880",
    "https://www.facebook.com/watch?ref=saved&v=1527875615126882",
    "https://www.facebook.com/watch?ref=saved&v=443712638554964",
    "https://www.facebook.com/watch?ref=saved&v=1768231697028127",
    "https://www.facebook.com/hunterrootmusic/posts/pfbid02vmUL3dpHtZjTD6JBibFXG24exHN4ryA7iQjeurqB7V1ZsFCHid7Hptcy9ukXZ5H4I",
    "https://www.facebook.com/watch?ref=saved&v=755734052557156",
    "https://www.facebook.com/hunterrootmusic/posts/pfbid032YCauaSRVzutjScTJ5gN72evb6mn8VkYrJsVKR3c4TSSXi3JZCbR8mMAzaM4gRzYI",
    "https://www.facebook.com/watch?ref=saved&v=3533165300277563",
    "https://www.facebook.com/watch?ref=saved&v=368621548505423",
    "https://www.facebook.com/hunterrootmusic/posts/pfbid0N5oZMiPNqp1VQu71Ar4DZQwcJEkkoUfZoQ3ToSfV6ixTeZQvM7w7SwBVgXx8NCW4I",
    "https://www.facebook.com/hunter.root.7/posts/pfbid02uq5uQhxXZXK1uMHshXmAKsJNW55qmqhoASnZ5kJiV5cucijEEvd2uHwrF58HdcGCI"
)

foreach ($url in $urls) {
    Start-Process "chrome.exe" $url
    Write-Host "Opened: $url"
    Read-Host "Press Enter to open next URL"
}
Write-Host "All URLs opened."
