<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"
    "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:py="http://purl.org/kid/ns#">
<head>
<script type="text/javascript" src=
"/htdocs/bazaarNew/js/opacity.js">
</script>
<link rel="shortcut icon" href=
"http://bazaar-vcs.org/Welcome?action=AttachFile&amp;do=get&amp;target=favicon.ico"
type="image/x-icon" />
<meta http-equiv="Content-Type" content=
"text/html; charset=us-ascii" />
<meta name="robots" content="index,follow" />
<title>Welcome - Bazaar Version Control</title>

<script type="text/javascript" src="http://bazaar-vcs.org/htdocs/common/js/common.js">
</script>
<script type="text/javascript">
//<![CDATA[
<!--// common functions

// We keep here the state of the search box
searchIsDisabled = false;

function searchChange(e) {
    // Update search buttons status according to search box content.
    // Ignore empty or whitespace search term.
    var value = e.value.replace(/\s+/, '');
    if (value == '' || searchIsDisabled) { 
        searchSetDisabled(true);
    } else {
        searchSetDisabled(false);
    }
}

function searchSetDisabled(flag) {
    // Enable or disable search
    document.getElementById('fullsearch').disabled = flag;
    document.getElementById('titlesearch').disabled = flag;
}

function searchFocus(e) {
    // Update search input content on focus
    if (e.value == 'Search') {
        e.value = '';
        e.className = '';
        searchIsDisabled = false;
    }
}

function searchBlur(e) {
    // Update search input content on blur
    if (e.value == '') {
        e.value = 'Search';
        e.className = 'disabled';
        searchIsDisabled = true;
    }
}

function actionsMenuInit(title) {
    // Initialize action menu
    for (i = 0; i < document.forms.length; i++) {
        var form = document.forms[i];
        if (form.className == 'actionsmenu') {
            // Check if this form needs update
            var div = form.getElementsByTagName('div')[0];
            var label = div.getElementsByTagName('label')[0];
            if (label) {
                // This is the first time: remove label and do buton.
                div.removeChild(label);
                var dobutton = div.getElementsByTagName('input')[0];
                div.removeChild(dobutton);
                // and add menu title
                var select = div.getElementsByTagName('select')[0];
                var item = document.createElement('option');
                item.appendChild(document.createTextNode(title));
                item.value = 'show';
                select.insertBefore(item, select.options[0]);
                select.selectedIndex = 0;
            }
        }
    }
}
//-->
//]]>
</script>
<link rel="stylesheet" type="text/css" charset="utf-8" media="all"
href="http://bazaar-vcs.org/htdocs/bazaarNew/css/common.css" />
<link rel="stylesheet" type="text/css" charset="utf-8" media=
"screen" href="http://bazaar-vcs.org/htdocs/bazaarNew/css/screen.css" />
<link rel="stylesheet" type="text/css" charset="utf-8" media=
"print" href="http://bazaar-vcs.org/htdocs/bazaarNew/css/print.css" />
<link rel="stylesheet" type="text/css" charset="utf-8" media=
"projection" href="http://bazaar-vcs.org/htdocs/bazaarNew/css/projection.css" />
<link rel="stylesheet" type="text/css" charset="utf-8" media=
"screen" href="http://bazaar-vcs.org/htdocs/bazaarNew/css/v4.css" />
<link rel="stylesheet" type="text/css" charset="utf-8" media=
"screen" href="http://bazaar-vcs.org/htdocs/bazaarNew/css/screen2.css" />
<link rel="stylesheet" type="text/css" charset="utf-8" media=
"screen" href="http://bazaar-vcs.org/htdocs/bazaarNew/css/twoColumnsRight.css" />
<link rel="alternate" title="Bazaar Version Control Recent Changes"
href="http://bazaar-vcs.org/RecentChanges?action=rss_rc&amp;ddiffs=1&amp;unique=1" type=
"application/rss+xml" />
<link rel="Start" href="http://bazaar-vcs.org/Welcome" />
<link rel="Alternate" title="Wiki Markup" href=
"http://bazaar-vcs.org/Welcome?action=raw" />
<link rel="Alternate" media="print" title="Print View" href=
"http://bazaar-vcs.org/Welcome?action=print" />
<link rel="Appendix" title="favicon.ico" href=
"http://bazaar-vcs.org/Welcome?action=AttachFile&amp;do=view&amp;target=favicon.ico" />
<link rel="Search" href="http://bazaar-vcs.org/FindPage" />
<link rel="Index" href="http://bazaar-vcs.org/TitleIndex" />
<link rel="Glossary" href="http://bazaar-vcs.org/WordIndex" />
<link rel="Help" href="http://bazaar-vcs.org/HelpOnFormatting" />
</head>
<body lang="en" dir="ltr" xml:lang="en">
<div id="page_header1_div"><script type="text/javascript">
//<![CDATA[
gui_editor_link_text = gui_editor_link_href = null;
//]]>
</script></div>
<div id="pageWrapper">
<hr class="hide" />
<div id="masthead" class="inside">
<div id="logoimage"><a href="http://bazaar-vcs.org/"><img src=
"http://bazaar-vcs.org/htdocs/bazaarNew/css/logo.png" width="144" height="149" alt=
"Bazaar" /></a></div>
<h1><a href="http://bazaar-vcs.org/">Bazaar</a></h1>
<p>GPL Distributed Version Control Software</p>
</div>
<hr class="hide" />
<div class="hnav">
<ul>
<li class="hide"><a class="hide" href="#skipToContent"><em>Skip
Navigation</em></a> <span class="divider">:</span></li>
<li><a href="http://bazaar-vcs.org/Documentation" id="hnav_learn" name=
"hnav_learn">Learn</a> <span class="divider">:</span></li>
<li><a href="http://bazaar-vcs.org/Download" id="hnav_get" name="hnav_get">Get</a>
<span class="divider">:</span></li>
<li><a href="http://bazaar-vcs.org/BzrSupport" id="hnav_community" name=
"hnav_community">Community</a> <span class="divider">:</span></li>
<li><a href="http://bazaar-vcs.org/BzrPlugins" id="hnav_plugins" name=
"hnav_plugins">Plugins</a></li>
</ul>
</div>
<div id="outerColumnContainer">
<div id="innerColumnContainer">
<hr class="hide" />
<div id="leftColumn">
<div class="inside"></div>
</div>
<hr class="hide" />
<div id="rightColumn">
<div class="inside">
<div id="searchbox">
<form name="search" method="get" action="" id="search">
<div><input type="hidden" name="action" value="fullsearch" id=
"fullsearch" /> <input type="hidden" name="context" value="180" />
<input type="hidden" name="fullsearch" value="Text" /> <label for=
"search_q">Search Bazaar</label> <input type="text" name="value"
id="search_q" value="" onfocus="searchFocus(this)" onblur=
"searchBlur(this)" onkeyup="searchChange(this)" onchange=
"searchChange(this)" alt="Search" /> <input type="submit" value=
"go" name="go" id="search_go" /></div>
</form>
</div>
<div id="searchform"></div>
<div id="username" class="vnav">
<h4>Website Links</h4>
<ul>
<li><a href="http://bazaar-vcs.org/AaronBentley">AaronBentley</a></li>
<li><a href="http://bazaar-vcs.org/UserPreferences">User Preferences</a></li>
<li><a href="http://bazaar-vcs.org/FindPage">FindPage</a></li>
<li><a href="http://bazaar-vcs.org/RecentChanges">RecentChanges</a></li>
<li><a name="editlink" href=
"http://bazaar-vcs.org/Welcome?action=edit&amp;editor=textonly" id="editlink">Edit
Page</a></li>
<li><a href="http://bazaar-vcs.org/Welcome?action=info">Page History</a></li>
<li><a href="http://bazaar-vcs.org/Welcome?action=subscribe">Subscribe</a></li>
<li>
<form class="actionsmenu" method="get" action="">
<div><label>More Actions:</label> <select name="action" onchange=
"if ((this.selectedIndex != 0) &amp;&amp; (this.options[this.selectedIndex].disabled == false)) { this.form.submit(); } this.selectedIndex = 0;">
<option value="raw">Raw Text</option>
<option value="print">Print View</option>
<option value="refresh">Delete Cache</option>
<option value="show" disabled="disabled" class="disabled">
------------</option>
<option value="SpellCheck">Check Spelling</option>
<option value="LikePages">Like Pages</option>
<option value="LocalSiteMap">Local Site Map</option>
<option value="show" disabled="disabled" class="disabled">
------------</option>
<option value="RenamePage">Rename Page</option>
<option value="DeletePage">Delete Page</option>
<option value="show" disabled="disabled" class="disabled">
------------</option>
<option value="AttachFile">Attach File</option>
<option value="Despam">Despam</option>
<option value="MyPages">My Pages</option>
<option value="PackagePages">Package Pages</option>
<option value="RenderAsDocbook">Render As Docbook</option>
<option value="SubscribeUser">Subscribe User</option>
</select> <input type="submit" value="Do" /></div>
<script type="text/javascript">
//<![CDATA[
<!--// Init menu
actionsMenuInit('More Actions:');
//-->
//]]>
</script></form>
</li>
</ul>
</div>
</div>
</div>
<div id="contentColumn" class="page_Welcome">
<hr class="hide" />
<div id="msg" class="vnav"></div>
<a name="skipToContent" id="skipToContent"></a>
<div class="inside" >
<!--<img id="navProtection" width="1" height="1" border="0" src="/htdocs/bazaarNew/css/spacer.gif" alt="" style="height: 1px"/>-->
<div dir="ltr" id="content" lang="en" xml:lang="en" py:content="body[:]"><span
class="anchor" id="top"></span> <span class="anchor" id="line-8"></span>
<h1 id="head-31592baed255c2a5cdfdaafb9521b837ea61021f">Performance
Drive Under Way</h1>
<span class="anchor" id="line-9"></span>
<p class="line879">There was substantial progress on performance
since 0.8. See <a href="/Performance/0.9">Performance/0.9</a>,
<a href="/Performance/0.10">Performance/0.10</a> and <a href=
"/Performance/0.11">Performance/0.11</a>. Thanks to everyone who
has contributed patches and ideas! The focus from here to 1.0 will
continue to be performance and documentation. Already there is work
in progress to: <span class="anchor" id="line-10"></span></p>
<span class="anchor" id="line-11"></span>
<ul>
<li>
<p class="line879">write a <a href="/SmartServer">SmartServer</a>
for high speed network operations (first look in 0.11).
<span class="anchor" id="line-12"></span></p>
</li>
<li>
<p class="line886">optimise file system access (tune our code and
data structures to minimise probable disk io and disk seeking)
<span class="anchor" id="line-13"></span></p>
</li>
<li>
<p class="line886">optimise file formats for performance without
sacrificing proven correctness and completeness <span class=
"anchor" id="line-14"></span></p>
</li>
<li>
<p class="line886">tune the codepaths that are most heavily used
<span class="anchor" id="line-15"></span></p>
</li>
<li>
<p class="line886">ensure that large imports are only done when
needed, and use lightweight imports where possible <span class=
"anchor" id="line-16"></span></p>
<span class="anchor" id="line-17"></span></li>
</ul>
<h1 id="head-ceb9b8e0146b0ce087048f495b2ff2964c5d57ec">News</h1>
<span class="anchor" id="line-18"></span>
<h2 id="head-39a1524e97c9a6ba89ecee7856cb1a2e68134373">27th
September 2006 - 0.11rc2 released</h2>
<span class="anchor" id="line-19"></span>
<p class="line879">bzr 0.11rc2 has been released. This release
candidate corrects two regressions that occured from 0.10. Windows
developers and users with very large source trees should upgrade
immediately. Release <a class="https" href=
"https://lists.canonical.com/archives/bazaar-ng/2006q3/017581.html">
announcement</a> or <a class="http" href=
"http://bazaar-vcs.org/releases/src/bzr-0.11rc2.tar.gz">download
now</a>. For details of the original 0.11 release candidate, see
the <a class="https" href=
"https://lists.canonical.com/archives/bazaar-ng/2006q3/017502.html">
announcement</a>. <span class="anchor" id="line-20"></span></p>
<span class="anchor" id="line-21"></span>
<h2 id="head-9940b3014f81c7b8ca65aa3235341588859d09dd">4th
September 2006 - 0.10 released</h2>
<span class="anchor" id="line-22"></span>
<p class="line879">bzr 0.10 has been released after a smooth beta
period. <a class="http" href=
"http://bazaar-vcs.org/releases/src/bzr-0.10.tar.gz">download it
now</a>! <span class="anchor" id="line-23"></span></p>
<span class="anchor" id="line-24"></span>
<h1 id="head-c2a87bc7d0bc411d33e18585154e534201115501">What is
Bazaar?</h1>
<span class="anchor" id="line-25"></span>
<p class="line879">Bazaar is a decentralized revision control
system designed to be easy for developers and end users alike.
Decentralized revision control systems give people the ability to
work over the internet using the <a class="http" href=
"http://en.wikipedia.org/wiki/The_Cathedral_and_the_Bazaar">bazaar
development model</a>. When you use Bazaar, you can commit to your
own branches of your favorite free software projects without
needing special permission. For more information, see: <span class=
"anchor" id="line-26"></span></p>
<span class="anchor" id="line-27"></span>
<ul>
<li>
<p class="line903"><a href="/Bzr">What Is Bazaar?</a> <span class=
"anchor" id="line-28"></span></p>
</li>
<li>
<p class="line903"><a href="/WhoUsesBzr">Who Uses Bazaar?</a>
<span class="anchor" id="line-29"></span></p>
</li>
<li>
<p class="line903"><a href="/BzrFeatures">Bazaar Features</a>
<span class="anchor" id="line-30"></span></p>
</li>
<li>
<p class="line903"><a href="/FAQ">FAQ</a> (Frequently Asked
Questions) <span class="anchor" id="line-31"></span></p>
</li>
<li>
<p class="line903"><a href="/BzrGlossary">Bazaar Glossary</a>
<span class="anchor" id="line-32"></span></p>
</li>
<li>
<p class="line903"><a href="/ReleaseRoadmap">What's Coming</a> (the
release roadmap) <span class="anchor" id="line-33"></span></p>
<span class="anchor" id="line-34"></span></li>
</ul>
<h1 id="head-54a84f21f8314a452aecfb4e2da59fcb246fee7b">Where do I
get it?</h1>
<span class="anchor" id="line-35"></span>
<p class="line886">The easiest place to get Bazaar is with your
distribution. Do not despair if your distribution does not have
Bazaar, as plain installation is still easy. <span class="anchor"
id="line-36"></span></p>
<span class="anchor" id="line-37"></span>
<ul>
<li>
<p class="line903"><a href="/DistroDownloads">Packages</a> -
Downloads for various distributions <span class="anchor" id=
"line-38"></span></p>
</li>
<li>
<p class="line903"><a href="/OfficialDownloads">Source</a> - Source
downloads <span class="anchor" id="line-39"></span></p>
</li>
<li>
<p class="line903"><a href="/WindowsDownloads">Windows</a> -
Downloads for windows <span class="anchor" id="line-40"></span></p>
<span class="anchor" id="line-41"></span></li>
</ul>
<h1 id="head-400b61668c5f3ab729ffbfeed0f9fc93e853044e">How do I
install it?</h1>
<span class="anchor" id="line-42"></span>
<p class="line879">Installation for Bazaar is a snap. Supported
operating systems include Linux, FreeBSD, Windows (Native &amp;
Cygwin) and Solaris. If you can run Python 2.4, then you can run
Bazaar. <span class="anchor" id="line-43"></span></p>
<span class="anchor" id="line-44"></span>
<ul>
<li>
<p class="line903"><a href="/DistroDownloads">Packages</a> -
Downloads for various distributions <span class="anchor" id=
"line-45"></span></p>
</li>
<li>
<p class="line903"><a href="/Installation">Generic</a> - Generic
Installation Instructions. <span class="anchor" id=
"line-46"></span></p>
</li>
<li>
<p class="line903"><a href="/BzrOnPureWindows">Native Windows</a> -
Installation of Bazaar on Native windows. <span class="anchor" id=
"line-47"></span></p>
<span class="anchor" id="line-48"></span></li>
</ul>
<h1 id="head-6350ee8bfd03b56b430e775595af1eb29ac7bdb4">How do I use
it?</h1>
<span class="anchor" id="line-49"></span>
<p class="line886">Included are the pearls of wisdom from people
that have already branched off into a new world of development.
<span class="anchor" id="line-50"></span></p>
<span class="anchor" id="line-51"></span>
<ul>
<li>
<p class="line903"><a href="/Documentation">Documents</a> - The
main documentation page for Bazaar. <span class="anchor" id=
"line-52"></span></p>
</li>
<li>
<p class="line903"><a href="/IntroductionToBzr">Introduction</a> -
Introduction to Bazaar gives a walkthough of the simpler commands.
<span class="anchor" id="line-53"></span></p>
</li>
<li>
<p class="line903"><a href="/QuickHackingWithBzr">Mini Tutorial</a>
- The five minutes Bazaar Tutorial. <span class="anchor" id=
"line-54"></span></p>
</li>
<li>
<p class="line903"><a href="/BzrRevisionSpec">Revision Specs</a> -
Arguments for -r that can be given with "bzr log", "bzr merge" and
such. <span class="anchor" id="line-55"></span></p>
<span class="anchor" id="line-56"></span></li>
</ul>
<h1 id="head-148c5debbd034308b67411c490e69555ee5a03a3">How does it
compare?</h1>
<span class="anchor" id="line-57"></span>
<p class="line886">If you're familiar with other version control
systems, you might like to see a quick comparison to them, or read
guidelines to help you understand how to use bzr most effectively
given your current experience. <span class="anchor" id=
"line-58"></span></p>
<span class="anchor" id="line-59"></span>
<ul>
<li>
<p class="line903"><a href="/BzrForCVSUsers">BzrForCVSUsers</a> -
Learning Bazaar for CVS users. <span class="anchor" id=
"line-60"></span></p>
</li>
<li>
<p class="line903"><a href="/BzrForGITUsers">BzrForGITUsers</a> -
(In progress) Learning Bazaar for GIT users <span class="anchor"
id="line-61"></span></p>
</li>
<li>
<p class="line903"><a href="/RcsComparisons">RcsComparisons</a> -
Comparison table of functionality and performance with Bazaar, GIT,
Mercurial, SVN and other VCS systems. <span class="anchor" id=
"line-62"></span></p>
<span class="anchor" id="line-63"></span></li>
</ul>
<h1 id="head-e966f9f6520262482dc713218b2a916600636f14">How can I
get Help?</h1>
<span class="anchor" id="line-64"></span>
<p class="line879">Our primary page for getting help is the
<a href="/BzrSupport">BzrSupport</a> page. <span class="anchor" id=
"line-65"></span></p>
<span class="anchor" id="line-66"></span>
<ul>
<li>
<p class="line903"><a class="https" href=
"https://launchpad.net/products/bzr/+bugs">Bug Tracker</a> - You
can check here to see if someone else is experiencing the same
problem that you are. <span class="anchor" id="line-67"></span></p>
</li>
<li>
<p class="line903"><a class="http" href=
"http://lists.canonical.com/mailman/listinfo/bazaar-ng">Mailing
List</a> - A high volume list focused upon Bazaar development and
support. <span class="anchor" id="line-68"></span></p>
</li>
<li>
<p class="line886">IRC - #bzr on irc.freenode.net <span class=
"anchor" id="line-69"></span></p>
<span class="anchor" id="line-70"></span></li>
</ul>
<h1 id="head-45d36005ff61e184525081c9c40ed26ded3c8f02">How can I
contribute?</h1>
<span class="anchor" id="line-71"></span>
<p class="line879">Our primary development doc page is <a href=
"/BzrDevelopment">BzrDevelopment</a>. <span class="anchor" id=
"line-72"></span></p>
<span class="anchor" id="line-73"></span>
<ul>
<li>
<p class="line903"><a href="/BzrDevelopment">Development
Instructions</a> - We keep our main development instructions here.
<span class="anchor" id="line-74"></span></p>
</li>
<li>
<p class="line903"><a href="/OfficialDownloads">Source Code</a> -
Source code to get hacking with. <span class="anchor" id=
"line-75"></span></p>
</li>
<li>
<p class="line903"><a class="https" href=
"https://launchpad.net/products/bzr/+specs">Specifications</a> -
Specifications list which things are being worked on today and are
likely to be worked on next. <span class="anchor" id=
"line-76"></span></p>
</li>
<li>
<p class="line903"><a class="https" href=
"https://launchpad.net/products/bzr/+bugs">BugTracker</a> - Open
bugs that you can work on. <span class="anchor" id=
"line-77"></span></p>
<span class="anchor" id="line-78"></span></li>
</ul>
<p class="line879">You are also welcome to improve this wiki site.
To edit pages, please <a href="/UserPreferences">register</a>.
Anonymous editing is disabled to prevent spammer attacks.
<span class="anchor" id="line-79"></span></p>
<span class="anchor" id="bottom"></span></div>
</div>
<div class="clear mozclear"></div>
</div>
</div>
<div class="hide" id="nsFooterClear"><!-- for NS4's sake --></div>
<hr class="hide" />
<div id="footer" class="inside">
<p style="margin:0;">&copy; 2006 - <a href=
"http://canonical.com/">Canonical Ltd.</a></p>
<div id="endofpage"></div>
<div id="footer_custom_html"></div>
<div id="footer_links"></div>
</div>
<hr class="hide" /></div>
</div>
</body>
</html>
