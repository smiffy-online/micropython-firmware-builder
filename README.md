# Micropython Firmware Builder

## History

Building Micropython from source is not for the faint-of-heart. There is a lot of building C packages, requiring a lot of parameters, and things outside of my areas of experience.

I started this, wanting two things:

- To be able to have hardware drivers and other modules baked-in to the Micropython image.
- To build a Micro:Bit Micropython firmware using the latest version of Micropython. (At the time, the base was a few years old.)

I did the original build with Claude Code, when it was the models were less sophisticated, and I was less experienced. We got something working, but it's not something I would want to offer to the community, as it takes a fair bit of work to get set up.

Original work in [v1](v1/)

## Roadmap - October 2026

* Start again, from scratch, taking the lessons learnt from the first build.
* Make setup as easy as possible, automate what can be automated, provide a guide for those parts that can't.
* Drive the whole thing through a Python/QT UI
* [optional] interface with flashing tools 

New work will be in [v2](v2)

